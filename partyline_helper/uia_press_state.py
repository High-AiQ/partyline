"""Narrow key preparation and observations: never walk the browser chrome for a URL."""

def kind(provider, node):
    if hasattr(provider, 'press_kind'):
        return provider.press_kind(node)
    return provider.properties(node).get('control_type')


def state(provider, node):
    if hasattr(provider, 'press_state'):
        return provider.press_state(node)
    return provider.properties(node)


def observation(provider, node):
    try:
        props = state(provider, node)
    except Exception:  # navigation may remove the field; the window title is still useful
        props = {}
    result = {key: props[key] for key in ('focused', 'value') if key in props}
    if props and provider.password(node):
        result.pop('value', None)
    root = provider.root()
    result['window_title'] = (provider.prop(root, 'Name') if hasattr(provider, 'press_state') else
                              provider.properties(root).get('name', ''))
    # Only an address control itself supplies URL evidence. No speculative traversal of page fields.
    if ('value' in result and props.get('control_type') == 'Edit' and
            (props.get('automation_id') in ('omnibox', 'addressEditBox') or
             str(props.get('name', '')).casefold() in
             ('address and search bar', 'search or enter web address'))):
        result['url'] = result['value']
    return result


class PressState:
    def press_kind(self, node):
        from .uia_windows import TYPES
        return TYPES.get(self.prop(node, 'ControlType'))

    def press_state(self, node):
        result = {'control_type': self.press_kind(node), 'name': self.prop(node, 'Name'),
                  'automation_id': self.prop(node, 'AutomationId'),
                  'focused': bool(self.prop(node, 'HasKeyboardFocus'))}
        if not self.password(node) and self.available(node, 10002):
            result['value'] = self.state_value(node, 'value', 10002, 'Value', 'CurrentValue')
        return result
