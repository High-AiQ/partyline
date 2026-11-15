"""Hidden upload inputs are discovered once, with stable actionable backend identities."""
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from partyline.screen_tree import Node, Snapshot
from partyline_helper.cdp_file_nodes import MAX_FILES, file_nodes, text
from partyline_helper.cdp_files import START
from partyline_helper.cdp_recipes import STATE
from partyline_helper.cdp_transport import CDPError
from tests.cdp_fakes import Fixture


def dom(tag, backend, children=(), **attrs):
    return dict(nodeName=tag, backendNodeId=backend, children=list(children),
                attributes=[part for pair in attrs.items() for part in pair])


def words(value):
    return dict(nodeName='#text', nodeValue=value)


class Discovery(TestCase):
    def test_labels_shadow_roots_frames_and_bounded_fallback_names(self):
        root = dom('#document', 1, [
            dom('INPUT', 10, type='file', id='upload'),
            dom('LABEL', 11, [words('Pick a file')], **{'for': 'upload'}),
            dict(dom('X-UPLOADER', 12), shadowRoots=[dom('#document-fragment', 13, [
                dom('INPUT', 14, type='file', **{'aria-label': 'Shadow file'})])]),
            dict(dom('IFRAME', 15), contentDocument=dom('#document', 16, [
                dom('INPUT', 17, type='FILE', accept='.txt'),
                dom('LABEL', 18, [dom('INPUT', 19, type='file'), words('Nested label')])])),
            dom('BUTTON', 20, [words('Choose'), dom('INPUT', 21, type='file')]),
            dom('INPUT', 22, type='file', name='attachment'),
            dom('INPUT', 23, type='file'), dom('INPUT', 24, type='text'),
            dom('INPUT', 25, type='file', id='named-upload', **{'aria-label': 'Accessible name'}),
            dom('LABEL', 26, [words('Fallback label')], **{'for': 'named-upload'})])
        found = file_nodes(root)
        self.assertEqual([node['backendDOMNodeId'] for node in found], [10, 14, 17, 19, 21, 22, 23, 25])
        self.assertEqual([node['name']['value'] for node in found],
                         ['Pick a file', 'Shadow file', '.txt', 'Nested label', 'Choose',
                          'attachment', 'File upload', 'Accessible name'])

    def test_caps_file_count_node_visits_and_text_work(self):
        root = dom('#document', 1, [dom('INPUT', i + 2, type='file') for i in range(200)])
        self.assertEqual(len(file_nodes(root)), MAX_FILES)
        with patch('partyline_helper.cdp_file_nodes.MAX_NODES', 3):
            self.assertEqual(len(file_nodes(root)), 2)
            wide = dom('#document', 1, [dom('DIV', 2, [dom('INPUT', 42, type='file')]),
                                       dom('DIV', 3), dom('DIV', 4)])
            self.assertEqual(file_nodes(wide)[0]['backendDOMNodeId'], 42)
        self.assertEqual(len(text(dom('LABEL', 1, [words('x' * 10000)]))), 240)
        self.assertEqual(text(dom('LABEL', 1, [words('x')] * 10000)), ' '.join(['x'] * 31))
        node = dom('DIV', 1)
        node['children'] = [node]
        self.assertEqual(file_nodes(node), [])

    def test_rendering_observation_is_file_only_and_does_not_hit_test(self):
        script = r'''
const state=RECIPE;
const element=(width,height,visibility)=>({tagName:'INPUT',type:'file',files:[],
 getRootNode:()=>({}),getBoundingClientRect:()=>({left:0,top:0,right:width,bottom:height,width,height}),
 closest:()=>null,matches:()=>false,
 ownerDocument:{activeElement:null,defaultView:{getComputedStyle:()=>({visibility})}}});
console.log(JSON.stringify([[0,0,'visible'],[10,10,'hidden'],[10,10,'visible']]
 .map(args=>state.call(element(...args)).hidden)));
const ordinary=element(10,10,'visible');
ordinary.type='text';
ordinary.ownerDocument.defaultView.getComputedStyle=()=>{throw Error('non-file style read')};
console.log(JSON.stringify(Object.hasOwn(state.call(ordinary),'hidden')));
'''.replace('RECIPE', STATE)
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        self.assertEqual(json.loads(lines[0]), [True, True, False])
        self.assertFalse(json.loads(lines[1]))
        self.assertNotIn('elementFromPoint', STATE)
        self.assertNotIn('innerText', STATE)


class HiddenFiles(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.f.socket.document = dom('#document', 1, [dom('INPUT', 42, type='file', id='attachment')])
        self.f.socket.states[42] = dict(tag='INPUT', type='file', hidden=True, files=[], file_count=0)

    async def test_continuation_reuses_discovery_and_ignored_ax_inputs_are_supplemented(self):
        self.f.socket.nodes = [dict(nodeId=str(n), role={'value': 'StaticText'}, name={'value': 'Text'})
                               for n in range(2001)]
        self.f.socket.nodes.append(dict(nodeId='ignored', backendDOMNodeId=42, ignored=True))
        first = await self.f.read()
        with patch('partyline.screen_tree.MAX_TREE', 2):
            tree = Snapshot('s', 0)
            tree.add(first['elements'])
        self.assertEqual([node.type for node in tree.nodes.values()], ['Text', 'FileInput'])
        rest = await self.f.read(cursor=first['next_cursor'])
        self.assertEqual(first['elements'][1]['control_type'], 'FileInput')
        self.assertFalse(any(item['control_type'] == 'FileInput' for item in rest['elements']))
        self.assertEqual(first['snapshot_id'], rest['snapshot_id'])
        self.assertEqual(sum(c['method'] == 'DOM.getDocument' for c in self.f.socket.calls), 1)

    async def test_read_identity_inspect_deduplication_and_visible_contract(self):
        result = await self.f.read()
        item = result['elements'][1]
        self.assertEqual((item['control_type'], item['name'], item['actions'], item['hidden']),
                         ('FileInput', 'attachment', ['set_files'], True))
        self.assertIn('hidden', Node(item).flags)
        self.assertTrue(Node(item).cached['hidden'])
        self.assertEqual((await self.f.read())['elements'][1]['id'], item['id'])
        inspected = await self.f.read(inspect=item['id'])
        self.assertTrue(inspected['live']['hidden'])
        self.assertEqual(inspected['live']['file_count'], 0)
        self.assertFalse(any(c['method'] == 'Accessibility.getPartialAXTree' for c in self.f.socket.calls))
        queries = [c for c in self.f.socket.calls if c['method'] == 'DOM.getDocument']
        self.assertEqual(len(queries), 2)
        self.assertEqual(queries[0]['params'], dict(depth=-1, pierce=True))
        self.f.socket.nodes.append(dict(nodeId='visible', backendDOMNodeId=42,
                                       role={'value': 'button'}, name={'value': 'Visible upload'}))
        visible = (await self.f.read())['elements'][-1]
        self.assertEqual(visible['id'], item['id'])
        self.assertEqual(visible['control_type'], 'Button')
        self.assertEqual(visible['name'], 'Visible upload')
        self.assertIn('invoke', visible['actions'])
        self.assertIn('set_files', visible['actions'])
        self.f.socket.nodes.pop()
        await self.f.read()
        self.f.socket.states[42]['type'] = 'text'
        self.assertIn('error', await self.f.read(inspect=item['id']))

    async def test_discovered_input_uses_existing_upload_guards_audit_and_readback(self):
        item = (await self.f.read())['elements'][1]
        page = await self.f.chrome.page(self.f.access)
        page.quiet.wait = AsyncMock(return_value='quiet')
        original = self.f.socket.response
        def response(message):
            if (message['method'] == 'Runtime.callFunctionOn'
                    and message['params']['functionDeclaration'] == START):
                return {'result': {'value': {'multiple': False}}}
            if message['method'] == 'DOM.setFileInputFiles':
                self.f.socket.states[42].update(files=['public.txt'], file_count=1)
            return original(message)
        self.f.socket.response = response
        with TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / 'helper'
            private.mkdir()
            secret = private / 'helper.json'
            secret.write_text('private')
            public = root / 'public.txt'
            public.write_text('file')
            message = dict(action='set_files', element_id=item['id'], paths=[str(public)],
                           file_limits={'file': 10, 'total': 20}, file_ticket='ticket')
            with patch('partyline_helper.cdp_files.config_path', return_value=secret), \
                 patch('partyline_helper.cdp_local_files.config_path', return_value=secret), \
                 patch('partyline_helper.cdp_local_files.audit_remote') as audit:
                for extra, error in (({'paths': [str(secret)]}, 'helper data'),
                                     ({'file_limits': {'file': 1, 'total': 20}}, 'per-file'),
                                     ({'paths': [str(public)] * 2}, 'multiple')):
                    result = await self.f.chrome.action(self.f.access, {**message, **extra})
                    self.assertEqual(result['status'], 'failed')
                    self.assertIn(error, result['error'])
                result = await self.f.chrome.action(self.f.access, message)
                self.assertEqual((result['status'], result['files'], result['count']),
                                 ('completed', ['public.txt'], 1))
                self.assertEqual(audit.call_args.args[-1], [{'path': str(public), 'bytes': 4}])
                self.assertIn('"paths":', self.f.session.tools.audit.append.call_args.args[-1])
            sent = [c for c in self.f.socket.calls if c['method'] == 'DOM.setFileInputFiles']
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]['params'], dict(backendNodeId=42, files=[str(public)]))
        self.f.access.gate.invalidate()
        with self.assertRaisesRegex(CDPError, 'revoked'):
            await page.snapshot()
