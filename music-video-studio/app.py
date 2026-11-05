import os, uuid, json, shutil, subprocess, threading
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv("DATA_DIR",str(BASE/"data")))
DATA.mkdir(parents=True,exist_ok=True)
MAX_IMAGE=15*1024*1024
MAX_AUDIO=150*1024*1024
JOB_LIMIT=1
JOB_TTL_SECONDS=3600

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
    """Chunk-driven MuseTalk 1.5. A dedicated GPU Space is required for full songs."""
    space=os.getenv("HF_SPACE_ID","").strip()
    endpoint=os.getenv("HF_API_NAME","/generate").strip()
    if not space:
        raise RuntimeError("AI singing needs a connected GPU model. Render has no configured HF_SPACE_ID.")
    from gradio_client import Client,handle_file
    client=Client(space,token=os.getenv("HF_TOKEN") or None)
    def mp4_from(response):
        if isinstance(response,str) and response.lower().split("?")[0].endswith(".mp4"):
            return response
        if isinstance(response,dict):
            for value in response.values():
                candidate=mp4_from(value)
                if candidate:return candidate
        if isinstance(response,(list,tuple)):
            for value in response:
                candidate=mp4_from(value)
                if candidate:return candidate
        return None
    length=duration(audio)
    chunk_seconds=int(os.getenv("LIPSYNC_CHUNK_SECONDS","12"))
    if not 4<=chunk_seconds<=30: raise RuntimeError("LIPSYNC_CHUNK_SECONDS must be from 4 to 30.")
    parts=[]
    for index,start in enumerate(range(0,int(length+0.9999),chunk_seconds)):
        remaining=length-start
        if remaining<=0:break
        segment=work/f"audio_{index:04d}.wav"
        run("ffmpeg","-y","-hide_banner","-loglevel","error","-ss",start,"-t",min(chunk_seconds,remaining),
            "-i",audio,"-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",segment)
        # Verified upstream function signature:
        # generate(audio_path, video_path, bbox_shift, extra_margin, parsing_mode,
        #          left_cheek_width, right_cheek_width).
        response=client.predict(handle_file(str(segment)),handle_file(str(photo)),
            0,10,"jaw",90,90,api_name=endpoint)
        generated=mp4_from(response)
        if not generated or not Path(generated).is_file():
            raise RuntimeError(f"MuseTalk returned no local MP4 for segment {index+1}. Check Space API and quota.")
        clip=work/f"clip_{index:04d}.mp4"
        run("ffmpeg","-y","-hide_banner","-loglevel","error","-i",generated,
            "-t",min(chunk_seconds,remaining),"-an",
            "-vf","scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=25,format=yuv420p",
            "-c:v","libx264","-preset","veryfast","-crf","25",clip)
        parts.append(clip)
    if not parts: raise RuntimeError("No lip-sync video segments returned")
    manifest=work/"clips.txt"
    manifest.write_text("".join("file '" + str(p.resolve()) + "'" + chr(10) for p in parts))
    joined=work/"joined.mp4"
    run("ffmpeg","-y","-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",manifest,
        "-c","copy",joined)
    # Last step uses original full-resolution soundtrack, replacing chunk audio.
    run("ffmpeg","-y","-hide_banner","-loglevel","error","-i",joined,"-i",audio,
        "-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","192k",
        "-shortest","-movflags","+faststart",out)

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
def health(): return {"ok":True,"lip_sync_configured":bool(os.getenv("HF_SPACE_ID")),"render_modes":["preview"]+(["lipsync"] if os.getenv("HF_SPACE_ID") else [])}

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
    with lock:
        active=sum(1 for j in jobs.values() if j["status"] in ("queued","processing"))
        if active>=JOB_LIMIT:raise HTTPException(429,"Another render is running. Try again later.")
    if mode=="lipsync" and not os.getenv("HF_SPACE_ID"):
        raise HTTPException(503,"Lip-sync GPU provider not configured yet. Use Photo-motion preview.")
    job=uuid.uuid4().hex
    folder=DATA/job;folder.mkdir()
    p=folder/"input_photo.png";a=folder/"input_audio"
    try:
        await save_upload(photo,p,MAX_IMAGE)
        await save_upload(song,a,MAX_AUDIO)
        with Image.open(p) as im: im.verify()
        with Image.open(p) as im:
            clean=ImageOps.exif_transpose(im).convert("RGB")
            if clean.width*clean.height > 25000000: raise HTTPException(413,"Image resolution too large")
            clean.save(folder/"normalized.png",format="PNG")
        (folder/"normalized.png").replace(p)
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
