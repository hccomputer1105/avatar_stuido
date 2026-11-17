import os
import io
import time
import asyncio
import threading
import requests
import replicate
import httpx
from replicate.exceptions import ReplicateError
import numpy as np
import edge_tts
from PIL import Image, ImageDraw, ImageOps
from moviepy.editor import ImageClip, AudioFileClip
from django.conf import settings
from django.core.files import File
from .models import Avatar, VideoProject


def _run_replicate_with_retry(model_id: str, input_data: dict, max_retries: int = 5):
    """Respeta el límite de 1 petición cada 10s y reintenta automáticamente ante error 429."""
    for attempt in range(max_retries):
        try:
            return replicate.run(model_id, input=input_data)
        except ReplicateError as e:
            if "429" in str(e) and attempt < max_retries - 1:
                print(f"[Replicate 429] Esperando 13 segundos antes de reintentar ({attempt + 1}/{max_retries})...")
                time.sleep(13)
            else:
                raise


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

    if choice == 'office':
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

    img.save(bg_path, format="JPEG", quality=90)
    return bg_path


def _get_or_create_cartoon_avatar(avatar: Avatar, oriented_img_path: str, temp_dir: str) -> str:
    """Genera la caricatura UNA sola vez y la guarda en el avatar para no volver a cobrarla."""
    if avatar.visual_style == 'original':
        return oriented_img_path

    # Si ya se generó y guardó previamente, reutilizarla sin gastar crédito en Replicate
    if avatar.processed_avatar and os.path.exists(avatar.processed_avatar.path):
        print(f"[Ahorro] Reutilizando avatar caricaturizado ya guardado para '{avatar.name}'.")
        return avatar.processed_avatar.path

    prompt = (
        "3D animated cartoon character portrait, Pixar style, expressive face, vibrant colors, studio lighting"
        if avatar.visual_style == 'cartoon_3d'
        else "2D stylized cartoon illustration character, clean lines, expressive portrait"
    )

    print("[Paso 1/3] Generando versión caricatura en Replicate...")
    with open(oriented_img_path, "rb") as img_file:
        output = _run_replicate_with_retry(
            "fofr/face-to-many:a07f252abbbd832009640b27f063ea52d87d7a23a185ca165bec23b5adc8deaf",
            {
                "image": img_file,
                "style": "3D" if avatar.visual_style == 'cartoon_3d' else "Anime",
                "prompt": prompt,
                "prompt_strength": 4.5,
            }
        )

    result_url = output[0] if isinstance(output, list) else str(output)
    img_data = requests.get(result_url).content

    cartoon_path = os.path.join(temp_dir, f"cartoon_avatar_{avatar.id}.jpg")
    with open(cartoon_path, 'wb') as f:
        f.write(img_data)

    # Guardar permanentemente en el modelo Avatar para reutilizarlo en futuros videos
    with open(cartoon_path, 'rb') as f:
        avatar.processed_avatar.save(f"cartoon_{avatar.id}.jpg", File(f), save=True)

    # Pausa obligatoria tras llamada a Replicate
    time.sleep(13)
    return avatar.processed_avatar.path


def _replace_background(avatar_img_path: str, bg_img_path: str, output_path: str) -> str:
    print("[Paso 2/3] Cambiando fondo del avatar en Replicate...")
    with open(avatar_img_path, 'rb') as img_file:
        nobg_url = _run_replicate_with_retry(
            "cjwbw/rembg:fb8af171cfa1616ddcf1242c093f9c46bcada5ad4cf6f2fbe8b81b330ec5c003",
            {"image": img_file}
        )

    fg_bytes = requests.get(str(nobg_url)).content
    foreground = Image.open(io.BytesIO(fg_bytes)).convert("RGBA")
    background = Image.open(bg_img_path).convert("RGBA").resize(foreground.size)

    combined = Image.alpha_composite(background, foreground).convert("RGB")
    combined.save(output_path, format="JPEG", quality=95)

    # Pausa obligatoria tras llamada a Replicate
    time.sleep(13)
    return output_path


def _animate_talking_head_cloud(avatar_path: str, audio_path: str, motion_style: str, output_video_path: str):
    print("[Paso 3/3] Generando video animado (boca y cabeza) en Replicate...")
    with open(avatar_path, "rb") as img_f, open(audio_path, "rb") as aud_f:
        video_url = _run_replicate_with_retry(
            "cjwbw/sadtalker:3aa3dac9353cc4d6bd62a8f95957bd844003b401ca4e4a9b33baa574c549d376",
            {
                "source_image": img_f,
                "driven_audio": aud_f,
                "preprocess": "full",
                "still_mode": False,
                "expression_scale": 1.35 if motion_style == 'expressive' else 1.0,
            }
        )

    video_bytes = requests.get(str(video_url)).content
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

        # 1. Obtener o generar caricatura (solo cobra la primera vez para ese avatar)
        current_img = _get_or_create_cartoon_avatar(video.avatar, oriented_img, temp_dir)

        # 2. Cambiar el Fondo (solo si no se eligió mantener el original)
        if video.background_choice != 'original':
            if video.background_choice == 'custom' and video.custom_background:
                bg_source = _fix_image_orientation(video.custom_background.path, temp_dir)
            else:
                bg_source = _get_preset_background(video.background_choice, temp_dir)
            current_img = _replace_background(current_img, bg_source, bg_applied_path)

        # 3. Generar Audio Neuronal desde el Guion
        asyncio.run(_generate_tts_audio(video.script_text, video.voice_id, audio_path))

        # 4. Generar Video Animado
        _animate_talking_head_cloud(current_img, audio_path, video.avatar.motion_style, final_video_path)

        # 5. Guardar el resultado final en Django
        with open(final_video_path, 'rb') as f:
            video.output_video.save(f"avatar_studio_{video.id}.mp4", File(f), save=False)

        video.status = VideoProject.Status.COMPLETED
        video.save()
        print(f"[OK] Video {video.id} completado con éxito.")

        # Limpiar archivos temporales
        for path in [oriented_img, bg_applied_path, audio_path, final_video_path]:
            if os.path.exists(path) and temp_dir in path:
                os.remove(path)

    except Exception as e:
        video = VideoProject.objects.get(id=video_id)
        video.status = VideoProject.Status.FAILED
        video.save()
        print(f"[ERROR VIDEO {video_id}]: {e}")


def start_video_job_async(video_id: int):
    thread = threading.Thread(target=process_video_generation, args=(video_id,), daemon=True)
    thread.start()
    import httpx

def _run_replicate_with_retry(model_id: str, input_data: dict, max_retries: int = 5):
    """Respeta el límite de velocidad y reintenta ante errores 429 o microcortes DNS/red."""
    for attempt in range(max_retries):
        try:
            return replicate.run(model_id, input=input_data)
        except Exception as e:
            err_msg = str(e)
            is_retryable = any(code in err_msg for code in ["429", "11001", "getaddrinfo", "ConnectError", "Timeout"])
            if is_retryable and attempt < max_retries - 1:
                print(f"[Reintento {attempt + 1}/{max_retries}] Esperando 13s por: {err_msg[:80]}...")
                time.sleep(13)
            else:
                raise