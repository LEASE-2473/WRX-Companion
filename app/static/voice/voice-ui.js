// 录音、STT与音频播放。会话持久化统一使用chat/companion.js。
function microphoneIsLive() { return Boolean(mediaStream?.getAudioTracks().some(track => track.readyState === 'live')); }

function releaseMicrophone() { if (microphoneReleaseTimer) clearTimeout(microphoneReleaseTimer); microphoneReleaseTimer = null; if (mediaStream) mediaStream.getTracks().forEach(track => track.stop()); mediaStream = null; }

function scheduleMicrophoneRelease() { if (microphoneReleaseTimer) clearTimeout(microphoneReleaseTimer); microphoneReleaseTimer = setTimeout(() => { if (!recording && !startPromise) releaseMicrophone(); }, MICROPHONE_WARM_IDLE_MS); }

async function acquireMicrophone() { if (microphoneReleaseTimer) clearTimeout(microphoneReleaseTimer); microphoneReleaseTimer = null; if (!microphoneIsLive()) mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true }); return mediaStream; }

async function prewarmMicrophoneIfGranted() { try { if (!navigator.permissions?.query) return; const permission = await navigator.permissions.query({ name: 'microphone' }); if (permission.state !== 'granted' || microphoneIsLive()) return; await acquireMicrophone(); scheduleMicrophoneRelease(); } catch {} }

function formatTime(value) { return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`; }

async function start() {
  if (recording || startPromise || processing) return;
  if (currentAudio && !currentAudio.paused) { status('请先中断当前播放'); return; }
  setConversationControlsDisabled(true);
  setConfigurationControlsDisabled(true);
  setTextInputControlsDisabled(true);
  stopping = false;
  status('Preparing Microphone');
  startPromise = (async () => {
    mediaStream = await acquireMicrophone();
    audioContext = new AudioContext();
    source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    chunks = [];
    pendingSttFrames = [];
    sttStream = null;
    processor.onaudioprocess = event => {
      if (!recording) return;
      const samples = new Float32Array(event.inputBuffer.getChannelData(0));
      chunks.push(samples);
      if (STT_INTEGRITY_MODE) return;
      const pcm = encodePcm16(samples, audioContext.sampleRate);
      if (sttStream?.ready && sttStream.socket.readyState === WebSocket.OPEN) sttStream.socket.send(pcm);
      else if (sttOpeningPromise) pendingSttFrames.push(pcm);
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    await audioContext.resume();
    recording = true;
    $('talk').classList.add('active');
    status('Listening');
    sttOpeningPromise = (STT_INTEGRITY_MODE ? Promise.resolve(null) : openStreamingStt()).then(state => {
      sttStream = state;
      if (state?.ready && state.socket.readyState === WebSocket.OPEN) pendingSttFrames.forEach(frame => state.socket.send(frame));
      pendingSttFrames = [];
      return state;
    });
  })();
  try { await startPromise; if (stopping) await stop(); } catch (error) { if (sttStream) { try { sttStream.socket.close(); } catch {} sttStream = null; } pendingSttFrames = []; releaseMicrophone(); setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false); status('Error'); alert(`无法开始录音：${error.message}`); } finally { startPromise = null; }
}


async function stop() {
  if (startPromise && !recording) { stopping = true; return; }
  if (finishPromise) return finishPromise;
  finishPromise = finishRecording().finally(() => { finishPromise = null; });
  return finishPromise;
}


async function finishRecording() {
  if (!recording || !audioContext) return;
  stopping = true;
  status('Finalizing Recording');
  const drainMs = Math.ceil(processor.bufferSize / audioContext.sampleRate * 1000) + 20;
  await new Promise(resolve => setTimeout(resolve, drainMs));
  if (!recording || !audioContext) return;
  recording = false;
  processor.onaudioprocess = null;
  source.disconnect();
  processor.disconnect();
  scheduleMicrophoneRelease();
  const releasedAt = performance.now();
  const sourceRate = audioContext.sampleRate;
  const data = new Float32Array(chunks.reduce((total, chunk) => total + chunk.length, 0));
  let offset = 0;
  chunks.forEach(chunk => { data.set(chunk, offset); offset += chunk.length; });
  const wav = encodeWav(data, sourceRate);
  await audioContext.close();
  audioContext = null;
  if (sttOpeningPromise) await sttOpeningPromise;
  sttOpeningPromise = null;
  stopping = false;
  $('talk').classList.remove('active');
  if (!data.length) { setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false); status('Idle'); return; }
  const streamed = await finishStreamingStt(releasedAt);
  await processAudio(wav, streamed, releasedAt, data.length / sourceRate);
}


async function processAudio(wav, streamed = null, requestStarted = performance.now(), recordingDuration = 0) {
  stopAudio();
  if (processing) return false;
  processing = true;
  setConversationControlsDisabled(true);
  setConfigurationControlsDisabled(true);
  setTextInputControlsDisabled(true);
  const requestConversationId = activeConversationId;
  status('Transcribing');
  let completed = false;
  try {
    await prepareStreamPlayback(requestStarted);
    let body = STT_INTEGRITY_MODE ? { audio_base64: b64(wav) } : streamed?.text ? { transcript: streamed.text, stt_latency: streamed.latency, recording_duration: recordingDuration, provider_snapshot_id: streamed.snapshotId || '' } : { audio_base64: b64(wav), provider_snapshot_id: streamed?.snapshotId || '' };
    body = {...body, conversation_id: requestConversationId, request_id: newIdentityId(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai', search_mode: $('searchMode').value};
    const result = await fetch('/api/process/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!result.ok) { const failure = await result.json(); throw new Error(failure.detail || '语音请求失败'); }
    if (!result.body) throw new Error('流式接口不可用');
    const reader = result.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let assistantNode;
    let transcript = '';
    const consume = async payload => {
      if (payload.type === 'state') status(payload.state);
      if (payload.type === 'search') renderSearchTurn(payload);
      if (payload.type === 'transcript') { transcript = payload.text; addMessage('user', transcript); status('Thinking'); }
      if (payload.type === 'delta') { if (!assistantNode) assistantNode = addMessage('assistant', ''); assistantNode.querySelector('.message-body').textContent += payload.text; scrollChat(); }
      if (payload.type === 'audio_chunk') schedulePcmChunk(payload.audio_base64, payload.sample_rate || 24000);
      if (payload.type === 'complete') { if (activeConversationId !== requestConversationId) throw new Error('当前对话已切换，本轮结果未写入页面'); messages = payload.messages; renderConversation(); saveLlmDebug(payload.debug); if (streamPlayback?.firstPlaybackAt) payload.latency.actual_first_playback = (streamPlayback.firstPlaybackAt - streamPlayback.requestStarted) / 1000; renderDebug(payload, transcript); await persistConversation(requestConversationId); completed = true; if (payload.audio_streamed) finishStreamPlayback(payload); else { discardPreparedStream(); if (!payload.error && payload.audio_base64) playAudio(payload); } if (payload.error) { status('Error'); alert(`语音生成失败，但回复文本已保留：${payload.error || 'TTS 未返回音频'}`); setTimeout(() => status('Idle'), 1500); } }
      if (payload.type === 'failure') { discardPreparedStream(); renderConversation(); renderDebug(payload); if (payload.audio_base64) playAudio(payload); alert(payload.detail); }
      if (payload.type === 'error') { if (payload.prompt_tokens) renderDebug(payload); throw new Error(payload.detail); }
    };
    while (true) { const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done }); const frames = buffer.split('\n\n'); buffer = frames.pop() || ''; for (const frame of frames) { const line = frame.split('\n').find(item => item.startsWith('data: ')); if (line) await consume(JSON.parse(line.slice(6))); } if (done) break; }
  } catch (error) { discardPreparedStream(); renderConversation(); if (error.message === 'No speech detected') { status('No speech detected'); setTimeout(() => status('Idle'), 1200); } else { status('Error'); alert(error.message); setTimeout(() => status('Idle'), 1500); } } finally { processing = false; setConversationControlsDisabled(false); setConfigurationControlsDisabled(false); setTextInputControlsDisabled(false); }
  return completed;
}


async function openStreamingStt() {
  if (settings?.mode !== 'real') return null;
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${scheme}://${location.host}/api/stt/stream`);
  const state = { socket, ready: false, settled: false, final: null, error: null, resolveFinal: null };
  const finalPromise = new Promise(resolve => { state.resolveFinal = resolve; });
  state.finalPromise = finalPromise;
  const readyPromise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('实时 STT 建连超时')), 5000);
    socket.onmessage = event => {
      const payload = JSON.parse(event.data);
      if (payload.type === 'ready') { clearTimeout(timer); state.ready = true; state.providerSnapshotId = payload.provider_snapshot_id || ''; resolve(); }
      if (payload.type === 'partial') state.partial = payload.text;
      if (payload.type === 'final') { state.settled = true; state.final = payload; state.resolveFinal(payload); }
      if (payload.type === 'error') { state.settled = true; state.error = payload.detail; state.resolveFinal(null); }
    };
    socket.onerror = () => { clearTimeout(timer); reject(new Error('实时 STT 连接失败')); };
    socket.onclose = () => { if (!state.settled) state.resolveFinal(null); };
  });
  try { await readyPromise; return state; } catch { try { socket.close(); } catch {} return null; }
}


async function finishStreamingStt(releasedAt) {
  const state = sttStream;
  sttStream = null;
  if (!state?.ready) return null;
  if (state.socket.readyState !== WebSocket.OPEN) return { text: '', snapshotId: state.providerSnapshotId || '' };
  state.socket.send(JSON.stringify({ type: 'finish' }));
  status('Transcribing');
  const timeout = new Promise(resolve => setTimeout(() => resolve(null), 10000));
  const result = await Promise.race([state.finalPromise, timeout]);
  try { state.socket.close(); } catch {}
  if (!result?.text?.trim()) return { text: '', snapshotId: state.providerSnapshotId || '' };
  return { text: result.text.trim(), latency: (performance.now() - releasedAt) / 1000, snapshotId: state.providerSnapshotId || '' };
}


async function prepareStreamPlayback(requestStarted) {
  const context = new AudioContext({ sampleRate: 24000 });
  await context.resume();
  streamPlayback = { context, sources: new Set(), nextAt: context.currentTime + 0.04, firstAt: null, firstPlaybackAt: null, requestStarted, finalOut: null, inputFinished: false, duration: 0, markTimer: null };
}


function pcmFromBase64(value) { const binary = atob(value); const bytes = new Uint8Array(binary.length); for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index); return new Int16Array(bytes.buffer); }

function schedulePcmChunk(encoded, sampleRate) {
  if (!streamPlayback) return;
  const pcm = pcmFromBase64(encoded);
  if (!pcm.length) return;
  const state = streamPlayback;
  const buffer = state.context.createBuffer(1, pcm.length, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;
  const node = state.context.createBufferSource();
  node.buffer = buffer;
  node.connect(state.context.destination);
  const startsAt = Math.max(state.nextAt, state.context.currentTime + 0.025);
  if (state.firstAt === null) {
    state.firstAt = startsAt;
    const delay = Math.max(0, (startsAt - state.context.currentTime) * 1000);
    state.markTimer = setTimeout(() => { if (streamPlayback !== state) return; state.firstPlaybackAt = performance.now(); status('Speaking'); if (state.finalOut) { state.finalOut.latency.actual_first_playback = (state.firstPlaybackAt - state.requestStarted) / 1000; renderDebug(state.finalOut); } }, delay);
  }
  state.nextAt = startsAt + buffer.duration;
  state.duration += buffer.duration;
  state.sources.add(node);
  node.onended = () => { state.sources.delete(node); if (state.inputFinished && !state.sources.size) finalizeStreamPlayback(state); };
  node.start(startsAt);
  status('Generating Voice');
}


function finishStreamPlayback(out) { if (!streamPlayback) { prepareCompletedAudio(out); status('Idle'); return; } streamPlayback.finalOut = out; streamPlayback.inputFinished = true; if (streamPlayback.firstPlaybackAt) { out.latency.actual_first_playback = (streamPlayback.firstPlaybackAt - streamPlayback.requestStarted) / 1000; renderDebug(out); } if (!streamPlayback.sources.size) finalizeStreamPlayback(streamPlayback); }

function finalizeStreamPlayback(state) { if (streamPlayback !== state) return; if (state.markTimer) clearTimeout(state.markTimer); state.context.close(); streamPlayback = null; if (state.finalOut?.audio_base64) prepareCompletedAudio(state.finalOut); status('Idle'); updatePlayback(); }

function discardPreparedStream() { if (!streamPlayback) return; const state = streamPlayback; if (state.markTimer) clearTimeout(state.markTimer); state.sources.forEach(node => { try { node.stop(); } catch {} }); state.context.close(); streamPlayback = null; }

function prepareCompletedAudio(out) { if (!out?.audio_base64) return false; currentAudio = new Audio(`data:${out.audio_mime};base64,${out.audio_base64}`); currentAudio.onloadedmetadata = updatePlayback; currentAudio.ontimeupdate = updatePlayback; currentAudio.onended = () => { updatePlayback(); status('Idle'); }; currentAudio.onerror = () => { currentAudio = null; updatePlayback(); status('Error'); }; return true; }

function playAudio(out) {
  stopAudio();
  const playbackPreparationStarted = performance.now();
  if (!prepareCompletedAudio(out)) { status('Error'); return; }
  currentAudio.onplaying = () => { out.latency.audio_playback_preparation = (performance.now() - playbackPreparationStarted) / 1000; renderDebug(out); };
  status('Speaking');
  currentAudio.play().catch(error => { status('Error'); alert(`播放失败：${error.message}`); });
}


function updatePlayback() { if (streamPlayback) { const state = streamPlayback; const current = state.firstAt === null ? 0 : Math.max(0, Math.min(state.duration, state.context.currentTime - state.firstAt)); $('playback').value = state.duration ? current / state.duration * 100 : 0; $('playbackTime').textContent = `${formatTime(current)} / ${formatTime(state.duration)}`; $('playPause').textContent = state.context.state === 'suspended' ? '播放' : '暂停'; return; } const audio = currentAudio; const duration = audio && Number.isFinite(audio.duration) ? audio.duration : 0; const current = audio ? audio.currentTime : 0; $('playback').value = duration ? (current / duration) * 100 : 0; $('playbackTime').textContent = `${formatTime(current)} / ${formatTime(duration)}`; $('playPause').textContent = audio && !audio.paused ? '暂停' : '播放'; }

function stopAudio() { discardPreparedStream(); if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio.onended = null; currentAudio = null; } updatePlayback(); }

function toggleAudio() { if (streamPlayback) { if (streamPlayback.context.state === 'suspended') { streamPlayback.context.resume(); status('Speaking'); } else { streamPlayback.context.suspend(); status('Paused'); } updatePlayback(); return; } if (!currentAudio) return; if (currentAudio.paused) { currentAudio.play(); status('Speaking'); } else { currentAudio.pause(); status('Paused'); } updatePlayback(); }

function beginTalkPointer(event) {
  if (!event.isPrimary || activeTalkPointerId !== null || (event.pointerType === 'mouse' && event.button !== 0)) return;
  event.preventDefault();
  activeTalkPointerId = event.pointerId;
  try { $('talk').setPointerCapture(event.pointerId); } catch {}
  void start();
}

function endTalkPointer(event) {
  if (activeTalkPointerId === null || event.pointerId !== activeTalkPointerId) return;
  event.preventDefault();
  const pointerId = activeTalkPointerId;
  activeTalkPointerId = null;
  try { if ($('talk').hasPointerCapture(pointerId)) $('talk').releasePointerCapture(pointerId); } catch {}
  void stop();
}

function b64(bytes) { let binary = ''; bytes.forEach(byte => { binary += String.fromCharCode(byte); }); return btoa(binary); }

function resample(samples, sourceRate, targetRate = 16000) { if (sourceRate === targetRate) return samples; const ratio = sourceRate / targetRate; const output = new Float32Array(Math.round(samples.length / ratio)); for (let i = 0; i < output.length; i += 1) { const start = Math.floor(i * ratio); const end = Math.min(samples.length, Math.floor((i + 1) * ratio)); let sum = 0; for (let j = start; j < end; j += 1) sum += samples[j]; output[i] = sum / Math.max(1, end - start); } return output; }

function encodePcm16(samples, sampleRate) { const pcm = resample(samples, sampleRate, 16000); const buffer = new ArrayBuffer(pcm.length * 2); const view = new DataView(buffer); pcm.forEach((sample, index) => view.setInt16(index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true)); return buffer; }

function encodeWav(samples, sampleRate) { const pcm = resample(samples, sampleRate, 16000); const outputRate = 16000; const buffer = new ArrayBuffer(44 + pcm.length * 2); const view = new DataView(buffer); const write = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0))); write(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); write(8, 'WAVEfmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, outputRate, true); view.setUint32(28, outputRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, pcm.length * 2, true); pcm.forEach((sample, index) => view.setInt16(44 + index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true)); return new Uint8Array(buffer); }

updatePlayback();
setInterval(updatePlayback, 200);
window.addEventListener('beforeunload', releaseMicrophone);

// 语音控件与热键；chat-ui随后限定热键适用范围。
$('talk').onpointerdown = beginTalkPointer;
$('talk').onpointerup = endTalkPointer;
$('talk').onpointercancel = endTalkPointer;
$('talk').onlostpointercapture = endTalkPointer;
window.onkeydown = event => { if (capturingKey) { event.preventDefault(); event.stopPropagation(); if (event.code === 'Escape') { capturingKey = false; pendingKey = key; $('keyInput').value = formatHotkey(key); $('captureKey').textContent = '录制按键'; setKeyState('已取消录制，原按键未变'); return; } pendingKey = event.code; capturingKey = false; $('keyInput').value = formatHotkey(pendingKey); $('captureKey').textContent = '重新录制'; setKeyState(`已录制 ${formatHotkey(pendingKey)}，点击“保存并立即生效”`, 'dirty'); return; } const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName); const managerOpen = Boolean(document.querySelector('.manager-dialog[open]')); if (!managerOpen && !editing && event.code === key && !event.repeat) { event.preventDefault(); start(); } };
window.onkeyup = event => { if (!capturingKey && event.code === key) { event.preventDefault(); stop(); } };
$('playPause').onclick = toggleAudio;
$('stopAudio').onclick = () => { stopAudio(); status('Idle'); };
$('playback').oninput = event => { if (currentAudio && Number.isFinite(currentAudio.duration)) currentAudio.currentTime = currentAudio.duration * event.target.value / 100; };
