"""Download authorized media to private temporary files and assign them to a CDP input."""
import asyncio
import contextlib
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .config import config_path
from .cdp_transport import CDPError

LIFETIME = 600
ACTIVE = set()
SCHEDULED = set()
START = r"""function(count) {
 if(this.tagName!=='INPUT' || this.type!=='file') return {error:'element is not a file input'};
 if(count>1 && !this.multiple) return {error:'file input does not accept multiple files'};
 const seen={input:0,change:0};
 this.__partylineFilesEvents=seen;
 for(const n of ['input','change']) this.addEventListener(n,()=>seen[n]++,{once:true});
 return {multiple:this.multiple};
}"""
FINISH = r"""function() {
 const seen=this.__partylineFilesEvents||{};
 for(const n of ['input','change']) if(!seen[n]) this.dispatchEvent(new Event(n,{bubbles:true}));
 delete this.__partylineFilesEvents;
 return {files:Array.from(this.files, f=>f.name), count:this.files.length};
}"""


def filename(value):
    name = str(value).replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:180]
    if len(name.encode('utf-8')) > 200:
        stem, dot, ext = name.rpartition('.')
        suffix = dot + ext if dot and len(ext.encode('utf-8')) <= 24 else ''
        prefix = stem if suffix else name
        name = prefix.encode('utf-8')[:200 - len(suffix.encode('utf-8'))].decode('utf-8', 'ignore') + suffix
    if not name or name.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        return 'file'
    return name


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CDPError("media download redirected")


def download(session, page, ticket, files, directory):
    paths = []
    for index, file in enumerate(files):
        page.guard()
        folder = directory / str(index)
        folder.mkdir()
        path = folder / filename(file['name'])
        request = Request(session.file_server + f'/api/screen/file-input/{ticket}/{index}',
                          headers={'Authorization': 'Bearer ' + session.file_token})
        count = 0
        opener = build_opener(ProxyHandler({}), NoRedirect)
        with opener.open(request, timeout=30) as response, path.open('xb') as output:
            while True:
                page.guard()
                chunk = response.read(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > file['bytes']:
                    raise CDPError('media download exceeded declared size')
                output.write(chunk)
        if count != file['bytes']:
            raise CDPError('media download size changed')
        paths.append(str(path))
    return paths


def schedule_cleanup(directory, delay=LIFETIME):
    if directory in SCHEDULED:
        return
    SCHEDULED.add(directory)
    def cleanup():
        SCHEDULED.discard(directory)
        shutil.rmtree(directory, ignore_errors=True)
    asyncio.get_running_loop().call_later(delay, cleanup)


async def set_files(page, message, backend):
    files = message['files']
    state = await page.function(backend, START, (len(files),))
    if state.get('error'):
        raise CDPError(state['error'])
    if len(files) > 1 and not state.get('multiple'):
        raise CDPError('file input does not accept multiple files')
    session = page.access.session
    root = config_path().parent / 'file-input'
    root.mkdir(parents=True, exist_ok=True)
    for old in root.iterdir():
        if old not in ACTIVE and old.is_dir():
            remaining = LIFETIME - (time.time() - old.stat().st_mtime)
            if remaining <= 0:
                shutil.rmtree(old, ignore_errors=True)
            else:
                schedule_cleanup(old, remaining)
    directory = Path(tempfile.mkdtemp(dir=root))
    ACTIVE.add(directory)
    task = asyncio.create_task(asyncio.to_thread(
        download, session, page, message['file_ticket'], files, directory))
    try:
        try:
            paths = await asyncio.shield(task)
        except (OSError, URLError) as exc:
            raise CDPError("media download failed; use the Open dialog path instead") from exc
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await task
            raise
        page.guard()
        if await session.chrome.page(page.access) is not page:
            raise CDPError('Chrome page changed during download; read the window again')
        page.guard()
        await page.call('DOM.setFileInputFiles', {'files': paths, 'backendNodeId': backend})
        observed = await page.function(backend, FINISH)
        # Chrome can hold File references after this command; remove staged bytes on a deadline.
        directory.touch()
        schedule_cleanup(directory)
        ACTIVE.discard(directory)
        directory = None
        return observed
    finally:
        if directory is not None:
            ACTIVE.discard(directory)
            shutil.rmtree(directory, ignore_errors=True)
