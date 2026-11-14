# Windows Chrome press live check

Status: **not run**; the implementation environment has no native Windows desktop.
Run on helper 1.2.0 or newer, with a Chrome window shared with the calling line.
Keep another app foreground and the pointer stationary. Record the helper/Chrome versions,
each full result, whether the foreground/pointer stayed unchanged, and the resulting page.
Do not enable desktop control or use `screen_key`/`screen_click` for this check.

The calls below are MCP calls with JSON arguments. `WINDOW` is the window grant id from
the share notice. Replace `ADDRESS`, `SEARCH`, and `SUBMIT` with ids returned by the
immediately preceding reads; these are response bindings, not literal ids. On a localized
Chrome, use the actual address-bar name from the first read instead of its English name.

1. `screen_elements({"window":"WINDOW"})`
2. `screen_elements({"window":"WINDOW","query":"Address and search bar","control_type":"Edit"})`
   Bind the address-bar element id as `ADDRESS`.
3. `screen_element_action({"window":"WINDOW","element_id":"ADDRESS","action":"set_value","value":"https://www.wikipedia.org/"})`
4. `screen_element_action({"window":"WINDOW","element_id":"ADDRESS","action":"press","key":"enter","then":{}})`
5. `screen_elements({"window":"WINDOW","refresh":true,"query":"Address and search bar","control_type":"Edit"})`
6. `screen_elements({"window":"WINDOW","control_type":"Edit"})`
   Confirm Wikipedia loaded, its title/address changed, and find the page search box
   (normally Search Wikipedia). Bind that field's id as `SEARCH`.
7. `screen_element_action({"window":"WINDOW","element_id":"SEARCH","action":"set_value","value":"Ada Lovelace"})`
8. `screen_element_action({"window":"WINDOW","element_id":"SEARCH","action":"press","key":"enter","then":{}})`
9. If step 8 returned `native_submit`, use its exact `query` and `control_type`:
   `screen_elements({"window":"WINDOW","query":"Search","control_type":"Button"})`
   Bind the matching button as `SUBMIT`, then
   `screen_element_action({"window":"WINDOW","element_id":"SUBMIT","action":"invoke","then":{}})`.
   Record this as a UIA-native submission; no key delivery was attempted in step 8.
10. `screen_elements({"window":"WINDOW","refresh":true,"text":true})`
11. `screen_elements({"window":"WINDOW","query":"Address and search bar","control_type":"Edit"})`

Expect Ada Lovelace content and a changed browser title/address or new elements after the
search. A result with `posted:3` alone does not pass. `no_effect` with unchanged immediate
and later observations is an honest unsupported target; record the hint and stop. If the
address navigation fails, stop before the search steps. If immediate `no_effect` is followed
by a changed `after` tree or later read, record the delayed effect separately. Do not retry
Enter automatically. Any foreground or mouse movement is a failed background-behavior check.

For explicit renderer-key validation, repeat steps 6–8 on an already open form whose search
field has no immediate-container Submit/Search/Go Invoke button. Step 8 should report
`delivery:"window_messages"`; record its immediate and later observations independently.
