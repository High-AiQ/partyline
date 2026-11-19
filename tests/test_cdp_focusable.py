"""Focusable generic elements and custom popup options use ordinary trusted input."""
import json
import subprocess
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from partyline_helper.cdp_control_details import CONTROL_DETAILS
from partyline_helper.cdp_dom_nodes import DETAIL, candidate, interactive_nodes
from partyline_helper.cdp_recipes import DISPATCH, HIT, STATE, normalize
from tests.cdp_fakes import Fixture
from tests.test_cdp_hidden_files import dom


class Normalization(TestCase):
    def test_standard_widget_roles_and_focusable_generic_actions(self):
        for role, control in (("option", "ListItem"), ("menuitemradio", "MenuItem"),
                              ("menuitemcheckbox", "MenuItem"), ("switch", "CheckBox"),
                              ("treeitem", "TreeItem"), ("gridcell", "DataItem")):
            with self.subTest(role=role):
                item = normalize(dict(backendDOMNodeId=2, role={"value": role}), 'i', None,
                                 dict(tag='X-OPTION', tabindex='-1'))
                self.assertEqual(item['control_type'], control)
                self.assertTrue({'invoke', 'select'} <= set(item['actions']))
        plain = normalize(dict(backendDOMNodeId=2, role={'value': 'generic'}), 'i', None,
                          dict(tag='DIV', focusable=True, short_text='Choose'))
        self.assertEqual(plain['name'], 'Choose')
        self.assertEqual(plain['actions'], ['scroll_into_view', 'press', 'invoke'])
        cell = normalize(dict(backendDOMNodeId=2, role={'value': 'gridcell'}), 'i', None, dict(tag='TD'))
        self.assertNotIn('select', cell['actions'])
        self.assertNotIn('invoke', cell['actions'])

    def test_name_sources_and_dom_role_fallback(self):
        node = dict(backendDOMNodeId=2, role={'value': 'generic'}, name={'value': 'Accessible'})
        state = dict(tag='DIV', role='option', aria_label='Label', title='Title', short_text='Text')
        for key, expected in (('name', 'Accessible'), ('aria_label', 'Label'),
                              ('title', 'Title'), ('short_text', 'Text')):
            self.assertEqual(normalize(node, 'i', None, state)['name'], expected)
            if key == 'name':
                node.pop('name')
            else:
                state.pop(key)
        self.assertEqual(normalize(node, 'i', None, state)['control_type'], 'ListItem')

    def test_discovery_is_bounded_and_pierces_shadow_roots_and_frames(self):
        trigger = dom('DIV', 4, tabindex='0')
        root = dom('#document', 1, [dict(dom('X-DROPDOWN', 2), shadowRoots=[
            dom('#document-fragment', 3, [trigger, dom('X-OPTION', 5, role='option', tabindex='-1')])]),
            dict(dom('IFRAME', 6), contentDocument=dom('#document', 7, [dom('BUTTON', 8)]))])
        nodes = [dict(nodeId='root', backendDOMNodeId=1),
                 dict(nodeId='ignored', backendDOMNodeId=4, ignored=True, role={'value': 'none'})]
        found = interactive_nodes(root, nodes)
        self.assertEqual([n['backendDOMNodeId'] for n in found], [4, 5, 6, 8])
        self.assertEqual(found[0]['parentId'], 'root')
        self.assertFalse(found[0]['ignored'])
        self.assertEqual(found[1]['role'], {'value': 'option'})
        with patch('partyline_helper.cdp_dom_nodes.MAX_NODES', 2):
            self.assertEqual(interactive_nodes(root, nodes), [])
        trigger['children'] = [trigger]
        with patch('partyline_helper.cdp_dom_nodes.MAX_NODES', 3):
            self.assertEqual(len(interactive_nodes(trigger, [])), 3)
        for tag, attrs in [('A', {'href': ''}), ('INPUT', {}), ('VIDEO', {'controls': ''}),
                           ('DIV', {'contenteditable': 'true'}), ('SUMMARY', {})]:
            self.assertTrue(candidate(tag, attrs))
        for attrs in ({'tabindex': '-1'}, {'tabindex': 'bad'}, {}):
            self.assertFalse(candidate('DIV', attrs))
        self.assertFalse(candidate('INPUT', {'type': 'hidden'}))


class Recipes(TestCase):
    def test_state_observes_focusability_without_text_or_hit_tests(self):
        script = r'''
const make=(tabIndex,native=false)=>({tagName:'DIV',tabIndex,closest:()=>null,
 matches:s=>s===':disabled'?false:native,getAttribute:()=>null,
 getRootNode:()=>({}),getBoundingClientRect:()=>({left:0,top:0,right:80,bottom:20,width:80,height:20}),
 ownerDocument:{activeElement:null}});
const elements=[make(0),make(-1),make(-1,true),make(-1)];
elements[3].isContentEditable=true;
console.log(JSON.stringify(elements.map(e=>(RECIPE).call(e).focusable)));
'''.replace('RECIPE', STATE)
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True, False, True, True])
        for forbidden in ('elementFromPoint', 'innerText', 'textContent', 'while('):
            self.assertNotIn(forbidden, STATE)

    def test_detail_reads_only_bounded_visible_text_and_visibility(self):
        script = r'''
let visits=0;
const view={getComputedStyle:n=>({display:n.hidden?'none':'block',visibility:n.visibility||'visible'})};
const text=value=>({nodeType:3,get nodeValue(){visits++;return value;}});
const el=(children=[],hidden=false)=>({nodeType:1,tagName:'DIV',hidden,childNodes:children,
 ownerDocument:{defaultView:view},getRootNode:()=>({}),getBoundingClientRect:()=>({width:80,height:20})});
const target=el([text(' Choose '),el([text('Hidden')],true),text(' option ')]);
const normal=(RECIPE).call(target);
target.shadowRoot={childNodes:[text('Shadow')]};
const shadow=(RECIPE).call(target);
const slot=el();slot.tagName='SLOT';slot.assignedNodes=()=>[text('Slotted')];
target.shadowRoot={childNodes:[slot]};const slotted=(RECIPE).call(target);
target.shadowRoot=null;target.childNodes=Array.from({length:10000},()=>text('x'));
visits=0;const wide=(RECIPE).call(target),count=visits;
target.childNodes=[text('x'.repeat(10000))];const long=(RECIPE).call(target);
target.visibility='hidden';const hidden=(RECIPE).call(target);
console.log(JSON.stringify({normal,shadow,slotted,wide,count,long,hidden}));
'''.replace('RECIPE', DETAIL)
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data['normal'], dict(hidden=False, short_text='Choose option'))
        self.assertEqual(data['shadow']['short_text'], 'Shadow')
        self.assertEqual(data['slotted']['short_text'], 'Slotted')
        self.assertLessEqual(data['count'], 31)
        self.assertEqual(len(data['long']['short_text']), 240)
        self.assertEqual(data['hidden'], dict(hidden=True))


class Reads(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)

    async def test_zero_size_ax_controls_keep_state_and_child_parent_links(self):
        self.f.socket.nodes.extend([
            dict(nodeId='4', parentId='1', backendDOMNodeId=4, role={'value': 'checkbox'}),
            dict(nodeId='5', parentId='4', role={'value': 'StaticText'}, name={'value': 'Check label'}),
            dict(nodeId='6', parentId='1', backendDOMNodeId=6, role={'value': 'link'},
                 name={'value': 'Floating link'}),
            dict(nodeId='7', parentId='6', role={'value': 'StaticText'}, name={'value': 'Link label'})])
        self.f.socket.states[4] = dict(tag='INPUT', type='checkbox', focusable=True,
                                       checked=True, hidden=True, bounds=[0, 0, 0, 0])
        self.f.socket.states[6] = dict(tag='A', focusable=True, hidden=True, bounds=[0, 0, 100, 0])
        elements = (await self.f.read())['elements']
        checkbox = next(n for n in elements if n['control_type'] == 'CheckBox')
        link = next(n for n in elements if n['name'] == 'Floating link')
        self.assertEqual(checkbox['toggle'], 1)
        for name, parent in (('Check label', checkbox), ('Link label', link)):
            self.assertEqual(next(n['parent'] for n in elements if n['name'] == name), parent['id'])
        self.assertIn('toggle', checkbox['actions'])
        self.assertIn('invoke', link['actions'])

    async def test_named_ax_controls_avoid_detail_but_unnamed_and_discovered_nodes_use_it(self):
        self.f.socket.states[2]['focusable'] = True
        self.f.socket.nodes.extend([
            dict(nodeId=str(backend), parentId='1', backendDOMNodeId=backend,
                 role={'value': role}, name={'value': name})
            for backend, role, name in ((4, 'button', 'Named action'), (5, 'generic', ''),
                                        (6, 'generic', ''), (7, 'generic', ''),
                                        (9, 'option', 'Named option'))])
        self.f.socket.states.update({
            4: dict(tag='BUTTON', focusable=True),
            5: dict(tag='DIV', focusable=True, aria_label='Label'),
            6: dict(tag='DIV', focusable=True, title='Title'),
            7: dict(tag='DIV', focusable=True, short_text='Fallback'),
            8: dict(tag='DIV', focusable=True, aria_label='Discovered'),
            9: dict(tag='X-OPTION', role='option')})
        self.f.socket.document = dom('#document', 1, [dom('DIV', 8, tabindex='0')])
        elements = (await self.f.read())['elements']
        details = [m['params']['objectId'] for m in self.f.socket.calls
                   if m['method'] == 'Runtime.callFunctionOn'
                   and m['params']['functionDeclaration'] == DETAIL]
        self.assertEqual(set(details), {'8'})
        batched = [m['params']['objectId'] for m in self.f.socket.calls
                   if m['method'] == 'Runtime.callFunctionOn'
                   and m['params']['functionDeclaration'] == CONTROL_DETAILS]
        self.assertEqual(batched, ['7'])
        self.assertTrue({'Named action', 'Label', 'Title', 'Fallback', 'Discovered', 'Named option'}
                        <= {n['name'] for n in elements})


class Popup(IsolatedAsyncioTestCase):
    async def test_fresh_read_after_trusted_invoke_discovers_visible_options(self):
        f = Fixture()
        self.addAsyncCleanup(f.close)
        f.socket.document = dom('#document', 1, [dict(dom('X-DROPDOWN', 10), shadowRoots=[
            dom('#document-fragment', 11, [dom('DIV', 12, tabindex='0'),
                                         dom('X-OPTION', 13, role='option', tabindex='-1')])])])
        f.socket.nodes.append(dict(nodeId='ignored', backendDOMNodeId=12, ignored=True))
        f.socket.states[12] = dict(tag='DIV', focusable=True, short_text='Choose', hit=True)
        f.socket.states[13] = dict(tag='X-OPTION', role='option', hidden=True, short_text='First', hit=True)
        first = await f.read()
        self.assertFalse(any(m['method'] == 'Runtime.callFunctionOn'
                             and m['params']['functionDeclaration'] == HIT for m in f.socket.calls))
        trigger = next(n for n in first['elements'] if n['name'] == 'Choose')
        self.assertNotIn('First', [n['name'] for n in first['elements']])
        self.assertEqual(trigger['actions'], ['scroll_into_view', 'press', 'invoke'])
        page = await f.chrome.page(f.access)
        page.quiet.wait = AsyncMock(return_value='quiet')
        def hook(message):
            if (message['method'] == 'Input.dispatchMouseEvent'
                    and message['params']['type'] == 'mouseReleased'):
                f.socket.states[13]['hidden'] = False
                f.socket.event()
        f.socket.hook = hook
        result = await f.chrome.action(f.access, dict(action='invoke', element_id=trigger['id']))
        self.assertEqual(result['status'], 'completed')
        recipes = [m['params']['functionDeclaration'] for m in f.socket.calls
                   if m['method'] == 'Runtime.callFunctionOn']
        self.assertIn(DISPATCH, recipes)
        after = await f.read()
        option = next(n for n in after['elements'] if n['name'] == 'First')
        self.assertTrue({'invoke', 'select'} <= set(option['actions']))
        self.assertEqual(next(n['id'] for n in after['elements'] if n['name'] == 'Choose'), trigger['id'])
        self.assertNotIn('error', await f.read(inspect=trigger['id']))
        self.assertEqual((await f.chrome.action(f.access, dict(action='select', element_id=option['id'])))
                         ['status'], 'completed')
        f.socket.states[12]['hit'] = False
        before = len([m for m in f.socket.calls if m['method'] == 'Input.dispatchMouseEvent'])
        self.assertEqual((await f.chrome.action(f.access, dict(action='invoke', element_id=trigger['id'])))
                         ['status'], 'failed')
        self.assertEqual(sum(m['method'] == 'Input.dispatchMouseEvent' for m in f.socket.calls), before)
        f.socket.states[13]['hidden'] = True
        self.assertIn('error', await f.read(inspect=option['id']))
        self.assertEqual((await f.chrome.action(f.access, dict(action='select', element_id=option['id'])))
                         ['status'], 'failed')
