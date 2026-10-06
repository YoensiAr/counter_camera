"use strict";
const $ = (id) => document.getElementById(id);
const form = $("line-form");
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let statusData = null, initialized = false, drawing = false, points = [], lastHistory = 0, serviceError = "";
let drawingKind = "line", draftRoi = null;
const canvas = $("line-canvas");
const ctx = canvas.getContext("2d");
function alertText(id, message) { $(id).textContent = message; $(id).hidden = !message; }
async function api(path, data) {
  const options = data === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify(data)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "No se pudo completar la solicitud.");
  return result;
}
function populate(line) {
  ["p1", "p2"].forEach(key => {form.elements[key+"x"].value = line[key][0]; form.elements[key+"y"].value = line[key][1];});
  ["entry_to", "margin_px", "confirmation_frames", "cooldown_seconds", "anchor"].forEach(key => form.elements[key].value = line[key]);
  draftRoi = line.roi || null;
}
function clearDrawing() {drawing = false; points = []; canvas.style.pointerEvents = "none"; canvas.style.cursor = "default"; ctx.clearRect(0,0,canvas.width,canvas.height); $("draw-line").textContent = "Dibujar línea"; $("draw-roi").textContent = "Delimitar acceso";}
function renderDraft() {
  canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#fce392"; ctx.strokeStyle = "#fce392"; ctx.lineWidth = 3;
  points.forEach(([x, y]) => {ctx.beginPath(); ctx.arc(x*canvas.width, y*canvas.height, 6,0,Math.PI*2); ctx.fill();});
  if (points.length === 2) {
    if (drawingKind === "roi") {ctx.strokeRect(points[0][0]*canvas.width, points[0][1]*canvas.height,(points[1][0]-points[0][0])*canvas.width,(points[1][1]-points[0][1])*canvas.height);}
    else {ctx.beginPath(); ctx.moveTo(points[0][0]*canvas.width, points[0][1]*canvas.height); ctx.lineTo(points[1][0]*canvas.width, points[1][1]*canvas.height); ctx.stroke();}
  }
}
$("draw-line").addEventListener("click", () => {
  if (drawing) {clearDrawing(); return;}
  drawingKind = "line"; drawing = true; points = []; canvas.style.pointerEvents = "auto"; canvas.style.cursor = "crosshair";
  $("draw-line").textContent = "Cancelar dibujo";
  alertText("notice", "Selecciona el inicio y el final de la línea sobre el video. Después pulsa Guardar configuración.");
});
$("draw-roi").addEventListener("click", () => {
  if (drawing) {clearDrawing(); return;}
  drawingKind="roi"; drawing=true; points=[]; canvas.style.pointerEvents="auto"; canvas.style.cursor="crosshair";
  $("draw-roi").textContent="Cancelar zona";
  alertText("notice","Selecciona dos esquinas opuestas alrededor del acceso. La línea debe atravesar esa zona. Después guarda la configuración.");
});
$("clear-roi").addEventListener("click",()=>{draftRoi=null; clearDrawing(); alertText("notice","Zona quitada del borrador. Guarda la configuración para contar en toda la imagen.");});
canvas.addEventListener("pointerdown", event => {
  if (!drawing) return;
  const rect = canvas.getBoundingClientRect();
  const clamp = value => Math.max(0, Math.min(1, value));
  points.push([Number(clamp((event.clientX-rect.left)/rect.width).toFixed(3)), Number(clamp((event.clientY-rect.top)/rect.height).toFixed(3))]);
  renderDraft();
  if (points.length === 2) {
    if (drawingKind === "roi") {
      draftRoi=[Math.min(points[0][0],points[1][0]),Math.min(points[0][1],points[1][1]),Math.max(points[0][0],points[1][0]),Math.max(points[0][1],points[1][1])];
      $("draw-roi").textContent="Redibujar acceso";
    } else {["p1", "p2"].forEach((key, index) => {form.elements[key+"x"].value=points[index][0]; form.elements[key+"y"].value=points[index][1];});}
    drawing = false; canvas.style.pointerEvents="none"; $("draw-line").textContent="Dibujar de nuevo";
  }
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]'); button.disabled = true;
  try {
    const line = {p1:[+form.elements.p1x.value,+form.elements.p1y.value],p2:[+form.elements.p2x.value,+form.elements.p2y.value],entry_to:form.elements.entry_to.value,
      margin_px:+form.elements.margin_px.value,confirmation_frames:+form.elements.confirmation_frames.value,cooldown_seconds:+form.elements.cooldown_seconds.value,anchor:form.elements.anchor.value,roi:draftRoi};
    await api("/api/line",line); clearDrawing(); alertText("notice","Línea guardada. El seguimiento está confirmando las nuevas posiciones."); alertText("error", "");
  } catch(error) {alertText("error",error.message);} finally {button.disabled=false;}
});
$("toggle-recording").addEventListener("click", async () => {
  if (!statusData) return;
  const enabled = !statusData.recording;
  try {await api("/api/recording",{enabled}); statusData.recording=enabled;
    alertText("notice",enabled?"Grabación activada. Los videos se guardan en este equipo.":"Grabación detenida.");
  } catch(error) {alertText("error",error.message);}
});
$("reset-button").addEventListener("click", () => $("reset-dialog").showModal());
$("cancel-reset").addEventListener("click", () => $("reset-dialog").close());
$("confirm-reset").addEventListener("click", async () => {
  $("confirm-reset").disabled=true;
  try {await api("/api/reset",{confirm:true}); $("reset-dialog").close(); alertText("notice","Ocupación reiniciada. Se conservan las entradas, salidas y referencias para evitar repeticiones.");}
  catch(error) {alertText("error",error.message);} finally {$("confirm-reset").disabled=false;}
});

const visitorForm = $("visitors-form");
function visitorHoursState() {visitorForm.elements.window_hours.disabled = visitorForm.elements.window.value !== "hours";}
function populateVisitors(settings) {
  visitorForm.elements.enabled.checked=settings.enabled;
  visitorForm.elements.window.value=settings.window;
  visitorForm.elements.window_hours.value=settings.window_hours;
  visitorHoursState();
}
visitorForm.elements.window.addEventListener("change", visitorHoursState);
visitorForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button=visitorForm.querySelector('button[type="submit"]'); button.disabled=true;
  try {
    const result=await api("/api/visitors", {enabled:visitorForm.elements.enabled.checked,window:visitorForm.elements.window.value,window_hours:+visitorForm.elements.window_hours.value});
    populateVisitors(result.visitors);
    alertText("notice","Plazo guardado. Se aplica también a las referencias que siguen vigentes, desde su primer cruce verificado.");
    alertText("error", "");
  } catch(error) {alertText("error",error.message);} finally {button.disabled=false;}
});
$("forget-visitors").addEventListener("click",()=>$("forget-dialog").showModal());
$("cancel-forget").addEventListener("click",()=>$("forget-dialog").close());
$("confirm-forget").addEventListener("click",async()=>{
  $("confirm-forget").disabled=true;
  try {await api("/api/visitors/forget",{confirm:true}); $("forget-dialog").close(); alertText("notice","Referencias de rostro y cuerpo eliminadas. Los totales históricos se conservan.");}
  catch(error) {alertText("error",error.message);} finally {$("confirm-forget").disabled=false;}
});

async function loadHistory() {
  const query = new URLSearchParams({start:$("start-date").value,end:$("end-date").value,group:$("group").value});
  const rows = await api("/api/history?"+query);
  $("csv-link").href="/reports/summary.csv?"+query;
  $("events-csv-link").href="/reports/events.csv?"+query;
  const tbody = $("history-body"); tbody.replaceChildren();
  if (!rows.length) {const row=tbody.insertRow(); const cell=row.insertCell(); cell.colSpan=7; cell.className="empty"; cell.textContent="No hay cruces registrados en este periodo."; return;}
  const max = Math.max(1,...rows.map(row=>Math.max(row.counted_entries,row.counted_exits)));
  for (const data of rows) {
    const row=tbody.insertRow();
    const dateLabel = data.period.length===10 ? data.period : data.period.slice(0,10)+" · "+data.period.slice(11,16)+" (UTC"+data.period.slice(19)+")";
    const unverified=data.unverified_entries+data.unverified_exits+data.pending_entries+data.pending_exits+data.unchecked_entries+data.unchecked_exits;
    [dateLabel,data.unique_visitors,data.returning_entries,unverified,data.counted_entries,data.counted_exits].forEach(text => row.insertCell().textContent=text);
    const bars=document.createElement("div"); bars.className="flow-bars";
    [data.counted_entries,data.counted_exits].forEach(value=>{const bar=document.createElement("span"); bar.style.width=(value/max*100)+"%"; bars.append(bar);});
    row.insertCell().append(bars);
  }
}
$("history-form").addEventListener("submit", async event=>{event.preventDefault();try{await loadHistory();alertText("error","");}catch(error){alertText("error",error.message);}});

let browserStream = null;
let browserCameraRunning = false;
let browserCameraTimer = null;
const browserVideo = $("browser-camera-source");
const uploadCanvas = $("browser-upload-canvas");
const uploadCtx = uploadCanvas.getContext("2d", {alpha:false});
const cameraSelect = $("browser-camera-select");

function cameraConstraints(deviceId) {
  return {
    audio: false,
    video: {
      deviceId: deviceId ? {exact: deviceId} : undefined,
      width: {ideal: statusData?.width || 640},
      height: {ideal: statusData?.height || 480},
      frameRate: {ideal: 10, max: 15},
      facingMode: deviceId ? undefined : {ideal: "environment"}
    }
  };
}

async function refreshCameraList() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
  const selected = cameraSelect.value;
  cameraSelect.replaceChildren();
  devices.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = device.label || `Cámara ${index + 1}`;
    cameraSelect.append(option);
  });
  if (devices.length) {
    cameraSelect.hidden = false;
    if ([...cameraSelect.options].some(o => o.value === selected)) cameraSelect.value = selected;
  }
}

async function stopBrowserCamera() {
  browserCameraRunning = false;
  if (browserCameraTimer) clearTimeout(browserCameraTimer);
  browserCameraTimer = null;
  if (browserStream) browserStream.getTracks().forEach(track => track.stop());
  browserStream = null;
  browserVideo.srcObject = null;
  $("start-browser-camera").hidden = false;
  $("stop-browser-camera").hidden = true;
  alertText("notice", "Cámara del navegador detenida.");
}

async function sendBrowserFrame() {
  if (!browserCameraRunning || !browserStream) return;
  const targetW = Math.max(160, Math.min(1280, statusData?.width || 640));
  const targetH = Math.max(120, Math.min(720, statusData?.height || 480));
  uploadCanvas.width = targetW;
  uploadCanvas.height = targetH;
  try {
    uploadCtx.drawImage(browserVideo, 0, 0, targetW, targetH);
    const blob = await new Promise(resolve => uploadCanvas.toBlob(resolve, "image/jpeg", 0.72));
    if (!blob) throw new Error("No se pudo comprimir el fotograma.");
    const response = await fetch("/api/camera/frame", {
      method: "POST",
      headers: {"Content-Type":"image/jpeg", "X-CSRF-Token":csrf},
      body: blob,
      cache: "no-store"
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    alertText("error", "");
  } catch (error) {
    if (browserCameraRunning) alertText("error", "No se pudo enviar la cámara al servidor: " + error.message);
  } finally {
    if (browserCameraRunning) browserCameraTimer = setTimeout(sendBrowserFrame, 100);
  }
}

async function startBrowserCamera(deviceId = "") {
  if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    throw new Error("El navegador solo permite usar la cámara desde HTTPS (o localhost). Abre el panel con https://");
  }
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Este navegador no soporta acceso a cámara con getUserMedia().");
  if (browserStream) browserStream.getTracks().forEach(track => track.stop());
  browserStream = await navigator.mediaDevices.getUserMedia(cameraConstraints(deviceId));
  browserVideo.srcObject = browserStream;
  await browserVideo.play();
  await refreshCameraList();
  const activeId = browserStream.getVideoTracks()[0]?.getSettings()?.deviceId;
  if (activeId && [...cameraSelect.options].some(o => o.value === activeId)) cameraSelect.value = activeId;
  browserCameraRunning = true;
  $("start-browser-camera").hidden = true;
  $("stop-browser-camera").hidden = false;
  alertText("notice", "Cámara conectada. Los fotogramas se están procesando con YOLO en el servidor.");
  sendBrowserFrame();
}

$("start-browser-camera").addEventListener("click", async () => {
  try { await startBrowserCamera(cameraSelect.value); }
  catch (error) { alertText("error", "No se pudo abrir la cámara: " + error.message); }
});
$("stop-browser-camera").addEventListener("click", stopBrowserCamera);
cameraSelect.addEventListener("change", async () => {
  if (!browserCameraRunning) return;
  try { browserCameraRunning = false; if (browserCameraTimer) clearTimeout(browserCameraTimer); await startBrowserCamera(cameraSelect.value); }
  catch (error) { alertText("error", "No se pudo cambiar de cámara: " + error.message); }
});
window.addEventListener("beforeunload", () => { if (browserStream) browserStream.getTracks().forEach(track => track.stop()); });

async function poll() {
  try {
    const s = await api("/api/status"); statusData=s;
    const v = s.visitors;
    $("unique-visitors").textContent=v.mode === "simulation" ? "—" : s.unique_visitors_today;
    $("returning-visitors").textContent=s.returning_entries_today;
    $("unverified-visitors").textContent=s.unverified_entries_today+s.unverified_exits_today+s.unchecked_entries_today+s.unchecked_exits_today;
    $("active-references").textContent=v.active_references+" referencias vigentes";
    $("unique-caption").textContent=v.window === "calendar_day" ? "Una primera entrada por persona y día" : "Primeras entradas de hoy dentro de cada plazo de "+v.window_hours+" h";
    const verifying=v.mode === "face" || v.mode === "hybrid";
    $("visitor-status").textContent=v.mode === "simulation" ? "Simulación: solo se prueban cruces físicos, sin identidades reales." : !v.enabled ? "Verificación desactivada: entradas y salidas cuentan cada cruce; no se evitan repeticiones." : !v.active ? "Preparando la verificación de visitantes…" : (v.mode === "hybrid" ? "Rostro + cuerpo + seguimiento · " : "Solo rostro · ")+s.pending_entries_today+" entradas y "+s.pending_exits_today+" salidas pendientes. Los casos dudosos no aumentan entradas ni salidas.";
    $("entries-caption").textContent=verifying ? "Una entrada por identidad estimada dentro del plazo" : "Cruces físicos · Sin verificación";
    $("exits-caption").textContent=verifying ? "Una salida por identidad estimada dentro del plazo" : "Cruces físicos · Sin verificación";
    $("occupancy").textContent=s.occupancy; $("entries").textContent=s.counted_entries_today; $("exits").textContent=s.counted_exits_today;
    $("camera-name").textContent=s.camera_name+(s.simulated?" · SIMULACIÓN":s.browser_camera?" · NAVEGADOR":"");
    $("browser-camera-bar").hidden=!s.browser_camera;
    $("camera-status").textContent=s.camera; $("camera-status").classList.toggle("offline", Boolean(s.camera_error||s.error));
    $("today").textContent=new Intl.DateTimeFormat("es-DO",{day:"numeric",month:"long",year:"numeric",timeZone:"UTC"}).format(new Date(s.date+"T12:00:00Z"));
    $("timezone").textContent=s.timezone; $("fps").textContent=s.fps.toFixed(1)+" FPS";
    $("latency").textContent=s.latency_ms.toFixed(0)+" ms"; $("model").textContent=s.model;
    $("tracker").textContent=s.tracker; $("memory").textContent=s.memory_mb.toFixed(1)+" MB"; $("dropped").textContent=s.dropped_frames;
    $("record-label").textContent=s.recording?"● Grabando":"Grabación desactivada";
    $("toggle-recording").textContent=s.recording?"Detener grabación":"Activar grabación";
    $("video-stage").style.aspectRatio=s.width+" / "+s.height;
    const issue=s.error||s.camera_error||s.recording_error||s.visitors.error||(s.inconsistent?"Hay más salidas que entradas. La ocupación se muestra en cero; revisa la dirección y el inicio del periodo.":s.occupancy_uncertain?"El seguimiento se interrumpió y pudo perder cruces. Revisa la ocupación; reiníciala cuando el local esté vacío.":"");
    if(issue) alertText("error",issue);
    else if(serviceError && $("error").textContent === serviceError) alertText("error", "");
    serviceError = issue;
    if (!initialized) {populateVisitors(s.visitors); populate(s.line); $("end-date").value=s.date; const start=new Date(s.date+"T12:00:00Z"); start.setUTCDate(start.getUTCDate()-6); $("start-date").value=start.toISOString().slice(0,10); initialized=true;}
    if(Date.now()-lastHistory>10000){await loadHistory(); lastHistory=Date.now();}
  } catch(error) {serviceError="No se puede conectar con el servicio. "+error.message; alertText("error",serviceError); $("camera-status").textContent="Sin conexión"; $("camera-status").classList.add("offline");}
  setTimeout(poll,1000);
}
$("video").addEventListener("error",()=>alertText("error","No se pudo abrir el video. Comprueba la cámara o cierra otras vistas del panel y recarga."));
poll();
