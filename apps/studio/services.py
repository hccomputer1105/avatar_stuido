import os
import io
import time
import asyncio
import threading
import traceback
import requests
import shutil
from dotenv import load_dotenv
load_dotenv(override=True)

import replicate
import numpy as np
import edge_tts
from PIL import Image, ImageDraw, ImageOps
from moviepy.editor import ImageClip, AudioFileClip
from django.conf import settings
from django.core.files import File
from .models import Avatar, VideoProject


def _get_replicate_client():
    """Lee el .env desde la raíz de Django, limpia espacios y crea un cliente fresco."""
    env_path = os.path.join(settings.BASE_DIR, '.env')
    load_dotenv(dotenv_path=env_path, override=True)
    token = os.getenv("REPLICATE_API_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        raise ValueError("REPLICATE_API_TOKEN está vacío en el archivo .env")
    return replicate.Client(api_token=token)


def _run_replicate_with_retry(model_id: str, input_data: dict, step_name: str, max_retries: int = 3, timeout_seconds: int = 480):
    """Crea la predicción y consulta su estado con límite de tiempo para evitar bucles infinitos."""
    print(f"---> Iniciando [{step_name}] usando modelo: {model_id}")
    client = _get_replicate_client()

    prediction = None
    for attempt in range(max_retries):
        try:
            if ":" in model_id:
                version_id = model_id.split(":", 1)[1]
                prediction = client.predictions.create(version=version_id, input=input_data)
            else:
                prediction = client.models.predictions.create(model=model_id, input=input_data)
            print(f"     ID de predicción creada: {prediction.id}")
            break
        except Exception as e:
            err_msg = str(e)
            print(f"[Fallo al iniciar {step_name} - intento {attempt + 1}/{max_retries}]: {err_msg}")
            if any(code in err_msg for code in ["429", "500", "502", "503", "504", "530"]) and attempt < max_retries - 1:
                time.sleep(12)
            else:
                raise

    start_time = time.time()
    consecutive_errors = 0

    while prediction.status not in ("succeeded", "failed", "canceled"):
        if time.time() - start_time > timeout_seconds:
            try:
                client.predictions.cancel(prediction.id)
            except Exception:
                pass
            raise TimeoutError(f"Tiempo límite de {timeout_seconds}s excedido esperando [{step_name}].")

        time.sleep(5)
        try:
            prediction = client.predictions.get(prediction.id)
            consecutive_errors = 0
            print(f"     Estado [{step_name}]: {prediction.status}")
        except Exception as e:
            consecutive_errors += 1
            print(f"[Aviso de red ({consecutive_errors}/8) consultando {step_name}]: {str(e)[:60]}...")
            if consecutive_errors >= 8:
                raise RuntimeError(f"Replicate devolvió error de red 8 veces seguidas en [{step_name}].")
            time.sleep(5)

    if prediction.status != "succeeded":
        raise RuntimeError(f"La predicción de {step_name} terminó con estado '{prediction.status}': {prediction.error}")

    return prediction.output


def _extract_bytes_from_output(output) -> bytes:
    """Extrae los bytes directamente de FileOutput, lista o URL devuelta por Replicate."""
    item = output[0] if isinstance(output, (list, tuple)) else output
    if hasattr(item, "read"):
        return item.read()
    url = item.url if hasattr(item, "url") else str(item)
    return requests.get(url).content


async def _generate_tts_audio(text: str, voice: str, output_audio_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_audio_path)


def _fix_image_orientation(image_path: str, temp_dir: str) -> str:
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    fixed_path = os.path.join(temp_dir, f"oriented_{os.path.basename(image_path)}")
    img.save(fixed_path, format="JPEG", quality=95)
    return fixed_path


def _get_preset_background(choice: str, temp_dir: str, size=(768, 768)) -> str:
    bg_path = os.path.join(temp_dir, f"bg_{choice}.jpg")
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)

    if choice == 'greenscreen':
        # Verde Chroma Key puro (#00FF00) estándar para edición de video
        img.paste((0, 255, 0))
    elif choice == 'office':
        for y in range(size[1]):
            r = int(210 - (y / size[1]) * 40)
            g = int(225 - (y / size[1]) * 35)
            b = int(245 - (y / size[1]) * 20)
            draw.line([(0, y), (size[0], y)], fill=(r, g, b))
    elif choice == 'studio':
        for y in range(size[1]):
            r = int(25 + (y / size[1]) * 35)
            g = int(30 + (y / size[1]) * 20)
            b = int(65 + (y / size[1]) * 55)
            draw.line([(0, y), (size[0], y)], fill=(r, g, b))
    else:
        img.paste((240, 240, 240))

    img.save(bg_path, format="JPEG", quality=98)
    return bg_path


def _get_or_create_cartoon_avatar(avatar: Avatar, oriented_img_path: str, temp_dir: str) -> str:
    """Convierte a caricatura usando modelo oficial activo en Replicate y guarda el resultado."""
    if avatar.visual_style == 'original':
        return oriented_img_path

    if avatar.processed_avatar and os.path.exists(avatar.processed_avatar.path):
        print(f"[Ahorro] Reutilizando avatar caricaturizado guardado para '{avatar.name}'.")
        return avatar.processed_avatar.path

    prompt = (
        "3D animated Pixar style cartoon character portrait, expressive face, clean studio lighting, high quality"
        if avatar.visual_style == 'cartoon_3d'
        else "2D stylized cartoon illustration character portrait, clean lines, vibrant colors"
    )

    with open(oriented_img_path, "rb") as img_file:
        output = _run_replicate_with_retry(
            "black-forest-labs/flux-kontext-pro",
            {
                "prompt": f"Transform this person into a {prompt}, keeping exact facial features and pose",
                "input_image": img_file,
                "output_format": "jpg"
            },
            step_name="Caricaturización"
        )

    img_data = _extract_bytes_from_output(output)
    cartoon_path = os.path.join(temp_dir, f"cartoon_avatar_{avatar.id}.jpg")
    with open(cartoon_path, 'wb') as f:
        f.write(img_data)

    with open(cartoon_path, 'rb') as f:
        avatar.processed_avatar.save(f"cartoon_{avatar.id}.jpg", File(f), save=True)

    return avatar.processed_avatar.path


def _replace_background(avatar_img_path: str, bg_img_path: str, output_path: str) -> str:
    """Recorta el fondo y aplica limpieza de bordes para Chroma Key limpio."""
    with open(avatar_img_path, 'rb') as img_file:
        nobg_output = _run_replicate_with_retry(
            "lucataco/remove-bg:95fcc2a26d3899cd6c2691c900465aaeff466285a65c14638cc5f36f34befaf1",
            {"image": img_file},
            step_name="Cambio de Fondo"
        )

    fg_bytes = _extract_bytes_from_output(nobg_output)
    foreground = Image.open(io.BytesIO(fg_bytes)).convert("RGBA")

    # Limpiar halos semitransparentes en los bordes si se usa fondo verde
    if "bg_greenscreen" in os.path.basename(bg_img_path):
        r, g, b, a = foreground.split()
        a = a.point(lambda p: 255 if p > 180 else 0)
        foreground = Image.merge("RGBA", (r, g, b, a))

    background = Image.open(bg_img_path).convert("RGBA").resize(foreground.size)
    combined = Image.alpha_composite(background, foreground).convert("RGB")
    combined.save(output_path, format="JPEG", quality=98)
    return output_path


def _animate_talking_head_cloud(avatar_path: str, audio_path: str, motion_style: str, output_video_path: str):
    """Anima imagen + audio usando bytedance/omni-human (o lucataco/sadtalker) con espera de hasta 8 min."""
    with open(avatar_path, "rb") as img_f, open(audio_path, "rb") as aud_f:
        video_output = _run_replicate_with_retry(
            "bytedance/omni-human",
            {
                "image": img_f,
                "audio": aud_f,
            },
            step_name="Animación de Avatar",
            timeout_seconds=480
        )

    video_bytes = _extract_bytes_from_output(video_output)
    with open(output_video_path, 'wb') as f:
        f.write(video_bytes)


def process_video_generation(video_id: int):
    try:
        video = VideoProject.objects.get(id=video_id)
        video.status = VideoProject.Status.PROCESSING
        video.save()

        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        oriented_img = _fix_image_orientation(video.avatar.source_image.path, temp_dir)
        bg_applied_path = os.path.join(temp_dir, f"bg_applied_{video.id}.jpg")
        audio_path = os.path.join(temp_dir, f"audio_{video.id}.mp3")
        final_video_path = os.path.join(temp_dir, f"video_{video.id}.mp4")

        # 1. Caricaturización
        current_img = _get_or_create_cartoon_avatar(video.avatar, oriented_img, temp_dir)

        # 2. Cambio de fondo
        if video.background_choice != 'original':
            if video.background_choice == 'custom' and video.custom_background:
                bg_source = _fix_image_orientation(video.custom_background.path, temp_dir)
            else:
                bg_source = _get_preset_background(video.background_choice, temp_dir)
            current_img = _replace_background(current_img, bg_source, bg_applied_path)

        # 3. Voz neuronal
        # 3. Generar o preparar el Audio según la elección del usuario
        if video.voice_mode == 'cloned' and video.avatar.voice_sample:
            _generate_cloned_voice_audio(
                video.script_text,
                video.avatar.voice_sample.path,
                audio_path
            )
        elif video.voice_mode == 'uploaded' and video.custom_audio:
            shutil.copy(video.custom_audio.path, audio_path)
        else:
            # Por defecto: Voz neuronal del sistema (Edge TTS)
            asyncio.run(_generate_tts_audio(video.script_text, video.voice_id, audio_path))

        # 4. Animación de boca, cabeza y manos
        _animate_talking_head_cloud(current_img, audio_path, video.avatar.motion_style, final_video_path)

        # 5. Guardar resultado
        with open(final_video_path, 'rb') as f:
            video.output_video.save(f"avatar_studio_{video.id}.mp4", File(f), save=False)

        video.status = VideoProject.Status.COMPLETED
        video.save()
        print(f"[OK] Video {video.id} completado con éxito.")

        for path in [oriented_img, bg_applied_path, audio_path, final_video_path]:
            if os.path.exists(path) and temp_dir in path:
                os.remove(path)

    except Exception as e:
        video = VideoProject.objects.get(id=video_id)
        video.status = VideoProject.Status.FAILED
        video.save()
        print(f"[ERROR VIDEO {video_id}]: {e}")
        traceback.print_exc()


def start_video_job_async(video_id: int):
    thread = threading.Thread(target=process_video_generation, args=(video_id,), daemon=True)
    thread.start()

import shutil

def _generate_cloned_voice_audio(text: str, speaker_audio_path: str, output_audio_path: str):
    """Replica la voz de la muestra del usuario leyendo el guion en español usando la versión vigente de XTTS-v2."""
    client = _get_replicate_client()
    model = client.models.get("lucataco/xtts-v2")
    latest_version_id = model.latest_version.id

    with open(speaker_audio_path, "rb") as speaker_f:
        audio_output = _run_replicate_with_retry(
            f"lucataco/xtts-v2:{latest_version_id}",
            {
                "text": text,
                "speaker": speaker_f,
                "language": "es",
                "cleanup_voice": True,
            },
            step_name="Clonación de Voz Propia"
        )

    audio_bytes = _extract_bytes_from_output(audio_output)
    with open(output_audio_path, 'wb') as f:
        f.write(audio_bytes)