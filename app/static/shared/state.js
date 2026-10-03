// 页面共享状态与实体身份；先于功能脚本加载。
function normalizeHotkey(value) { const trimmed = String(value || '').trim(); if (/^[a-z]$/i.test(trimmed)) return `Key${trimmed.toUpperCase()}`; if (/^[0-9]$/.test(trimmed)) return `Digit${trimmed}`; return trimmed || 'Space'; }

const issuedIdentityIds = new Set();
function newIdentityId(exists = () => false) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (;;) {
    let raw = '';
    while (raw.length < 16) {
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      for (const b of bytes) { if (b < 248 && raw.length < 16) raw += alphabet[b % 62]; }
    }
    const id = raw.match(/.{4}/g).join('-');
    if (!issuedIdentityIds.has(id) && !exists(id)) { issuedIdentityIds.add(id); return id; }
  }
}
const $ = id => document.getElementById(id);
const STT_INTEGRITY_MODE = true;
const MICROPHONE_WARM_IDLE_MS = 60000;
let settings;
let messages = [];
let conversations = [];
let activeConversationId = null;
let conversationExpanded = false;
let mediaStream;
let audioContext;
let sttStream;
let processor;
let source;
let chunks = [];
let recording = false;
let stopping = false;
let startPromise = null;
let finishPromise = null;
let activeTalkPointerId = null;
let sttOpeningPromise = null;
let pendingSttFrames = [];
let microphoneReleaseTimer = null;
let key = normalizeHotkey(localStorage.pttKey || 'Space');
let pendingKey = key;
let capturingKey = false;
let currentAudio;
let streamPlayback;
let processing = false;
let lastLlmDebug = null;
let draggedPromptIdentifier = null;
let pendingPromptImport = null;
let promptDirty = false;
let draggedLoreEntryId = null;
let pendingLorebookImport = null;
let lorebookDirty = false;
let lastLorebookTrace = null;
let pendingVectorImport = null;
let selectedVectorImportFile = null;
let inspectedVectorLibraryId = null;
let vectorChunkOffset = 0;
const VECTOR_CHUNK_PAGE_SIZE = 20;
