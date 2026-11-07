<script lang="ts">
  import SettingRow from "../SettingRow.svelte";
  import { handsFree } from "../../../state/hands-free.svelte.js";
</script>

<SettingRow
  id="setting-voice-pause"
  label="Hands-free speech pause"
  control="voiceSpeechPause"
  description="How long to wait after speech before transcribing and sending automatically. Saved on this device."
>
  <select
    id="voiceSpeechPause"
    value={handsFree.value.pauseMs}
    onchange={(event) => {
      handsFree.update({ pauseMs: Number(event.currentTarget.value) });
    }}
  >
    <option value={600}>0.6 seconds</option>
    <option value={1200}>1.2 seconds</option>
    <option value={1400}>1.4 seconds (default)</option>
    <option value={1500}>1.5 seconds</option>
    <option value={2000}>2 seconds</option>
    <option value={3000}>3 seconds</option>
  </select>
</SettingRow>
<SettingRow
  id="setting-voice-hidden"
  label="Release hidden microphone"
  control="voiceHiddenTimeout"
  description="Hands-free releases the mic and discards unfinished takes after this long in a hidden tab. Returning resumes listening automatically."
>
  <select
    id="voiceHiddenTimeout"
    value={handsFree.value.hiddenMs}
    onchange={(event) => {
      handsFree.update({ hiddenMs: Number(event.currentTarget.value) });
    }}
  >
    <option value={10000}>10 seconds</option>
    <option value={60000}>1 minute (default)</option>
    <option value={300000}>5 minutes</option>
    <option value={600000}>10 minutes</option>
  </select>
</SettingRow>
