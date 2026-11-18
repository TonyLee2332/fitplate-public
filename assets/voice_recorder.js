export default function({parentElement, data, setTriggerValue}) {
    const root=document.createElement('div');
    root.style.cssText='font:14px/1.5 system-ui;color:inherit;padding:6px 0';
    const row=document.createElement('div');row.style.cssText='display:flex;gap:8px;flex-wrap:wrap;align-items:center';
    const button=(label)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.style.cssText='font:16px system-ui;padding:9px 13px;border:1px solid #d7d5ce;border-radius:10px;background:#ffffff88;color:#454640;min-height:44px;cursor:pointer';row.append(b);return b;};
    const start=button(data.record), stop=button(data.stop), upload=button(data.upload), use=button(data.use);
    start.textContent='';
    start.setAttribute('aria-label',data.record);
    start.setAttribute('title',data.record);
    start.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';
    start.style.cssText+=';width:44px;padding:10px;display:inline-flex;align-items:center;justify-content:center;color:#747779';
    stop.hidden=true;use.hidden=true;
    const status=document.createElement('div');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const preview=document.createElement('audio');preview.controls=true;preview.setAttribute('playsinline','');preview.hidden=true;preview.style.cssText='width:100%;margin-top:8px';
    const input=document.createElement('input');input.type='file';input.accept='audio/*,.m4a,.webm,.mp4,.caf,.3gp';input.hidden=true;
    root.append(row,status,preview,input);parentElement.append(root);
    let stream=null, recorder=null, chunks=[], timer=null, permissionTimer=null, url=null, blob=null, filename='', disposed=false, attempt=0;
    const release=()=>{clearInterval(timer);clearTimeout(permissionTimer);stream?.getTracks().forEach(t=>t.stop());stream=null;};
    const idle=()=>{start.disabled=false;upload.disabled=false;stop.hidden=true;};
    const show=(value,name)=>{
        if(disposed)return;
        if(!value.size || value.size>10*1024*1024){status.textContent=data.invalid;return;}
        if(url)URL.revokeObjectURL(url);blob=value;filename=name;url=URL.createObjectURL(value);
        preview.src=url;preview.hidden=false;use.hidden=false;use.disabled=false;status.textContent=data.review;
    };
    upload.onclick=()=>{attempt++;release();idle();input.click();};
    input.onchange=()=>{if(input.files[0])show(input.files[0],input.files[0].name);input.value='';};
    start.onclick=async()=>{
        if(!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder==='undefined'){
            status.textContent=data.unsupported;return;
        }
        const captureAttempt=++attempt;
        start.disabled=true;upload.disabled=true;use.hidden=true;preview.hidden=true;blob=null;
        status.textContent=data.permission;
        permissionTimer=setTimeout(()=>{if(!disposed){status.textContent=data.pending;upload.disabled=false;}},12000);
        try {
            const acquired=await navigator.mediaDevices.getUserMedia({audio:true,video:false});
            if(disposed || captureAttempt!==attempt){acquired.getTracks().forEach(t=>t.stop());return;}
            stream=acquired;clearTimeout(permissionTimer);
            const mime=['audio/mp4','audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'].find(t=>typeof MediaRecorder.isTypeSupported==='function' && MediaRecorder.isTypeSupported(t));
            recorder=mime?new MediaRecorder(stream,{mimeType:mime}):new MediaRecorder(stream);
            chunks=[];let bytes=0;
            recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>10*1024*1024 && recorder.state==='recording')recorder.stop();}};
            recorder.onerror=()=>{release();idle();status.textContent=data.failed;};
            recorder.onstop=()=>{release();idle();const type=recorder.mimeType||mime||'audio/webm';show(new Blob(chunks,{type}),type.includes('mp4')?'recording.m4a':type.includes('ogg')?'recording.ogg':'recording.webm');};
            recorder.start(1000);stop.hidden=false;let seconds=0;status.textContent=data.recording+' 0s';
            timer=setInterval(()=>{seconds++;status.textContent=data.recording+' '+seconds+'s';if(seconds>=59 && recorder.state==='recording')recorder.stop();},1000);
        }catch(error){if(disposed || captureAttempt!==attempt)return;release();idle();status.textContent=error.name==='NotAllowedError'||error.name==='SecurityError'?data.denied:error.name==='NotFoundError'?data.missing:data.failed;}
    };
    stop.onclick=()=>{if(recorder?.state==='recording')recorder.stop();};
    use.onclick=()=>{
        if(!blob)return;use.disabled=true;const reader=new FileReader();
        reader.onload=()=>{if(disposed)return;const note=document.querySelector('[data-testid="stChatInput"] textarea')?.value||'';
            setTriggerValue('recording',{id:globalThis.crypto?.randomUUID?.()||String(Date.now())+Math.random(),name:filename,base64:String(reader.result).split(',')[1],note});status.textContent=data.sending;};
        reader.onerror=()=>{use.disabled=false;status.textContent=data.failed;};reader.readAsDataURL(blob);
    };
    return ()=>{disposed=true;if(recorder?.state==='recording'){recorder.onstop=null;recorder.stop();}release();if(url)URL.revokeObjectURL(url);root.remove();};
}
