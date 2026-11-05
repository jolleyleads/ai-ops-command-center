import os, uuid, json, shutil, subprocess, threading
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv("DATA_DIR",str(BASE/"data")))
DATA.mkdir(parents=True,exist_ok=True)
MAX_IMAGE=15*1024*1024
MAX_AUDIO=150*1024*1024
app=FastAPI(title="AI Music Video Studio",version="0.1.0")
jobs={}
lock=threading.Lock()

def run(*args):
    p=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=7200)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-1800:])
    return p.stdout

def duration(file):
    return float(json.loads(run("ffprobe","-v","error","-show_entries","format=duration","-of","json",file))["format"]["duration"])

def update(job,**kwargs):
    with lock: jobs[job].update(kwargs)

def portrait(photo, output):
    with Image.open(photo) as im:
        im=ImageOps.exif_transpose(im).convert("RGB")
        bg=ImageOps.fit(im,(720,1280),method=Image.Resampling.LANCZOS)
        bg=bg.filter(ImageFilter.GaussianBlur(35))
        bg=ImageEnhance.Brightness(bg).enhance(.35)
        fg=ImageOps.contain(im,(690,1000))
        bg.paste(fg,((720-fg.width)//2,(1280-fg.height)//2))
        bg.save(output,quality=91)

def preview(photo,audio,out,work):
    still=work/"portrait.jpg"
    portrait(photo,still)
    run("ffmpeg","-y","-hide_banner","-loglevel","error","-loop","1","-framerate","25","-i",still,"-i",audio,
        "-filter_complex","[0:v]zoompan=z='min(zoom+0.00012,1.07)':d=1:s=720x1280:fps=25,format=yuv420p[v]",
        "-map","[v]","-map","1:a:0","-c:v","libx264","-preset","veryfast","-crf","25","-c:a","aac","-b:a","192k",
        "-shortest","-movflags","+faststart",out)

def lipsync(photo,audio,out,work):
    space=os.getenv("HF_SPACE_ID","").strip()
    endpoint=os.getenv("HF_API_NAME","").strip()
    if not space or not endpoint:
        raise RuntimeError("Lip-sync GPU provider is not configured. Set HF_SPACE_ID and HF_API_NAME for a tested MuseTalk Gradio Space.")
    from gradio_client import Client,handle_file
    client=Client(space,token=os.getenv("HF_TOKEN") or None)
    # The target Space must expose a documented API taking image and audio file inputs in this order.
    # This fails explicitly for incompatible Spaces rather than pretending a still video is lip-synced.
    result=client.predict(handle_file(str(photo)),handle_file(str(audio)),api_name=endpoint)
    def find_mp4(value):
        if isinstance(value,str) and value.lower().endswith(".mp4"): return value
        if isinstance(value,dict):
            for v in value.values():
                got=find_mp4(v)
                if got:return got
        if isinstance(value,(tuple,list)):
            for v in value:
                got=find_mp4(v)
                if got:return got
        return None
    generated=find_mp4(result)
    if not generated or not Path(generated).is_file():
        raise RuntimeError("Lip-sync provider did not return a local MP4. Check its API contract.")
    # Preserve original song rather than using provider audio, and normalize to 9:16.
    run("ffmpeg","-y","-hide_banner","-loglevel","error","-stream_loop","-1","-i",generated,"-i",audio,
        "-vf","scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=25,format=yuv420p",
        "-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","veryfast","-crf","24",
        "-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",out)

def work_job(job,photo,audio,mode):
    folder=DATA/job
    try:
        update(job,status="processing",progress=15)
        output=folder/"music_video.mp4"
        if mode=="lipsync": lipsync(photo,audio,output,folder)
        else: preview(photo,audio,output,folder)
        if not output.exists() or output.stat().st_size<1024: raise RuntimeError("Empty render output")
        update(job,status="complete",progress=100,download=f"/api/jobs/{job}/download")
    except Exception as exc:
        update(job,status="failed",error=str(exc)[:500],progress=0)

@app.get("/",response_class=HTMLResponse)
def home(): return (BASE/"index.html").read_text()

@app.get("/health")
def health(): return {"ok":True,"lip_sync_configured":bool(os.getenv("HF_SPACE_ID") and os.getenv("HF_API_NAME"))}

async def save_upload(upload,path,limit):
    count=0
    with path.open("wb") as f:
        while chunk:=await upload.read(1024*1024):
            count+=len(chunk)
            if count>limit:
                path.unlink(missing_ok=True)
                raise HTTPException(413,"Upload exceeds size limit")
            f.write(chunk)
    if count==0: raise HTTPException(400,"Empty upload")

@app.post("/api/jobs",status_code=202)
async def new_job(photo:UploadFile=File(...),song:UploadFile=File(...),mode:str=Form("preview"),consent:str=Form("false")):
    if mode not in ("preview","lipsync"):raise HTTPException(400,"Invalid mode")
    if consent!="true":raise HTTPException(400,"Confirm you have rights to the face, voice and music.")
    if photo.content_type not in ("image/jpeg","image/png","image/webp"):raise HTTPException(415,"Use JPG, PNG or WebP.")
    if song.content_type not in ("audio/mpeg","audio/mp3","audio/mp4","audio/x-m4a","audio/wav","audio/x-wav","audio/ogg","application/octet-stream"):
        raise HTTPException(415,"Use MP3, WAV or M4A.")
    job=uuid.uuid4().hex
    folder=DATA/job;folder.mkdir()
    p=folder/"input_photo";a=folder/"input_audio"
    try:
        await save_upload(photo,p,MAX_IMAGE)
        await save_upload(song,a,MAX_AUDIO)
        with Image.open(p) as im: im.verify()
        seconds=duration(a)
        if not 1<=seconds<=600:raise HTTPException(400,"Song must be 1 second to 10 minutes.")
    except HTTPException:
        shutil.rmtree(folder,ignore_errors=True);raise
    except Exception:
        shutil.rmtree(folder,ignore_errors=True);raise HTTPException(400,"Invalid photo or audio.")
    with lock:jobs[job]={"id":job,"status":"queued","progress":0,"mode":mode,"duration_seconds":round(seconds,1)}
    threading.Thread(target=work_job,args=(job,p,a,mode),daemon=True).start()
    return jobs[job]

@app.get("/api/jobs/{job}")
def get_job(job:str):
    if job not in jobs: raise HTTPException(404,"Unknown job")
    return jobs[job]

@app.get("/api/jobs/{job}/download")
def download(job:str):
    if job not in jobs or jobs[job]["status"]!="complete":raise HTTPException(404,"Video not available")
    return FileResponse(DATA/job/"music_video.mp4",media_type="video/mp4",filename=f"music-video-{job[:8]}.mp4")
