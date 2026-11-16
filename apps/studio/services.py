import os
import time
import io
import asyncio
import threading
import requests
import replicate
import numpy as np
import edge_tts
from PIL import Image, ImageDraw
from moviepy.editor import ImageClip, AudioFileClip
from django.conf import settings
from django.core.files import File
from .models import Avatar, VideoProject


async def _generate_tts_audio(text: str, voice: str, output_audio_path: str):
    """Genera el archivo de audio neuronal a partir del guion."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_audio_path)


def _get_preset_background(choice: str, temp_dir: str, size=(768, 768)) -> str:
    """Genera o recupera una imagen de fondo según la elección del usuario."""
    bg_path = os.path.join(temp_dir, f"bg_{choice}.jpg")
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)

    # Paletas de colores para fondos predefinidos si no hay imagen subida
    if choice == 'office':
        # Degradado azul corporativo claro
        for y in range(size[1]):
            r = int(210 - (y / size[1]) * 40)
            g = int(225 - (y / size[1]) * 35)
            b = int(245 - (y / size[1]) * 20)
            draw.line([(0, y), (size[0], y)], fill=(r, g, b))
    elif choice == 'studio':
        # Degradado oscuro estilo estudio de podcast/noticias
        for y in range(size[1]):
            r = int(25 + (y / size[1]) * 35)
            g = int(30 + (y / size[1]) * 20)
            b = int(65 + (y / size[1]) * 55)
            draw.line([(0, y), (size[0], y)], fill=(r, g, b))
    else:
        img.paste((240, 240, 240))

    img.save(bg_path, format="JPEG", quality=90)
    return bg_path


def _stylize_to_cartoon(image_path: str, style: str, output_path: str) -> str:
    """Convierte el retrato en caricatura 3D o 2D usando Replicate."""
    if style == 'original' or not os.getenv("REPLICATE_API_TOKEN"):
        return image_path

    prompt = (
        "3D animated cartoon character portrait, Pixar style, expressive face, vibrant colors, studio lighting"
        if style == 'cartoon_3d'
        else "2D stylized cartoon illustration character, clean lines, expressive portrait"
    )

    with open(image_path, "rb") as img_file:
        output = replicate.run(
            "fofr/face-to-many:a07f252abbbd832009640b27f063ea52d87d7a23a185ca165bec23b5adc8deaf",
            input={
                "image": img_file,
                "style": "3D" if style == 'cartoon_3d' else "Anime",
                "prompt": prompt,
                "prompt_strength": 4.5,
            }
        )

    result_url = output[0] if isinstance(output, list) else str(output)
    img_data = requests.get(result_url).content
    with open(output_path, 'wb') as f:
        f.write(img_data)
    return output_path


def _replace_background(avatar_img_path: str, bg_img_path: str, output_path: str) -> str:
    """Recorta la silueta de la persona en la nube y la fusiona con el nuevo fondo."""
    if not os.getenv("REPLICATE_API_TOKEN"):
        return avatar_img_path

    with open(avatar_img_path, 'rb') as img_file:
        nobg_url = replicate.run(
            "cjwbw/rembg:fb8af171cfa1616ddcf1242c093f9c46bcada5ad4cf6f2fbe8b81b330ec5c003",
            input={"image": img_file}
        )

    fg_bytes = requests.get(str(nobg_url)).content
    foreground = Image.open(io.BytesIO(fg_bytes)).convert("RGBA")
    background = Image.open(bg_img_path).convert("RGBA").resize(foreground.size)

    combined = Image.alpha_composite(background, foreground).convert("RGB")
    combined.save(output_path, format="JPEG", quality=95)
    return output_path


def _animate_local_fallback(img_path: str, audio_path: str, motion_style: str, intensity: float, output_path: str):
    """Generador local de respaldo cuando no hay token de Replicate configurado."""
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    base_clip = ImageClip(img_path).set_duration(duration)

    def animate_frame(get_frame, t):
        frame = get_frame(t)
        h, w, _ = frame.shape
        scale = 1.0 + (0.05 * intensity * abs(np.sin(1.5 * t)))
        new_w, new_h = int(w / scale), int(h / scale)
        x1, y1 = (w - new_w) // 2, (h - new_h) // 2
        cropped = frame[y1:y1 + new_h, x1:x1 + new_w]
        return np.array(Image.fromarray(cropped).resize((w, h), Image.Resampling.LANCZOS))

    animated_clip = base_clip.fl(animate_frame).set_audio(audio_clip)
    animated_clip.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', logger=None)
    audio_clip.close()
    animated_clip.close()


def _animate_talking_head_cloud(avatar_path: str, audio_path: str, motion_style: str, output_video_path: str):
    """Anima boca, cabeza y gestos expresivos sincronizados con el audio usando IA."""
    with open(avatar_path, "rb") as img_f, open(audio_path, "rb") as aud_f:
        video_url = replicate.run(
            "cjwbw/sadtalker:3aa3dac9353cc4d6bd62a8f95957bd844003b401ca4e4a9b33baa574c549d376",
            input={
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
    """Orquestador completo: Caricatura -> Cambio de Fondo -> Voz -> Animación de Boca/Cabeza."""
    try:
        video = VideoProject.objects.get(id=video_id)
        video.status = VideoProject.Status.PROCESSING
        video.save()

        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        # Rutas temporales del pipeline
        current_img = video.avatar.source_image.path
        cartoon_img_path = os.path.join(temp_dir, f"cartoon_{video.id}.jpg")
        bg_applied_path = os.path.join(temp_dir, f"bg_applied_{video.id}.jpg")
        audio_path = os.path.join(temp_dir, f"audio_{video.id}.mp3")
        final_video_path = os.path.join(temp_dir, f"video_{video.id}.mp4")

        # 1. Convertir a Caricatura (si fue seleccionado y hay API Token)
        if video.avatar.visual_style != 'original':
            current_img = _stylize_to_cartoon(current_img, video.avatar.visual_style, cartoon_img_path)

        # 2. Cambiar el Fondo (si el usuario no eligió mantener el original)
        if video.background_choice != 'original':
            if video.background_choice == 'custom' and video.custom_background:
                bg_source = video.custom_background.path
            else:
                bg_source = _get_preset_background(video.background_choice, temp_dir)
            current_img = _replace_background(current_img, bg_source, bg_applied_path)

        # 3. Generar Audio Neuronal desde el Guion
        asyncio.run(_generate_tts_audio(video.script_text, video.voice_id, audio_path))

        # 4. Generar Video Animado (Nube con Lip-Sync si hay token, o Local de respaldo)
        if os.getenv("REPLICATE_API_TOKEN"):
            _animate_talking_head_cloud(current_img, audio_path, video.avatar.motion_style, final_video_path)
        else:
            _animate_local_fallback(
                current_img,
                audio_path,
                video.avatar.motion_style,
                video.avatar.motion_intensity,
                final_video_path
            )

        # 5. Guardar el resultado final en Django
        with open(final_video_path, 'rb') as f:
            video.output_video.save(f"avatar_studio_{video.id}.mp4", File(f), save=False)

        video.status = VideoProject.Status.COMPLETED
        video.save()

        # Limpiar archivos temporales
        for path in [cartoon_img_path, bg_applied_path, audio_path, final_video_path]:
            if os.path.exists(path):
                os.remove(path)

    except Exception as e:
        video = VideoProject.objects.get(id=video_id)
        video.status = VideoProject.Status.FAILED
        video.save()
        print(f"[ERROR VIDEO {video_id}]: {e}")

        token = os.getenv("REPLICATE_API_TOKEN", "").strip()
        has_valid_replicate = bool(token and not token.startswith("r8_pon_aqui"))

        # 1. Convertir a Caricatura
        if video.avatar.visual_style != 'original':
            if has_valid_replicate:
                current_img = _stylize_to_cartoon(current_img, video.avatar.visual_style, cartoon_img_path)
            else:
                current_img = _stylize_local_cartoon(current_img, video.avatar.visual_style, cartoon_img_path)

        # 2. Cambiar el Fondo
        if video.background_choice != 'original':
            if video.background_choice == 'custom' and video.custom_background:
                bg_source = video.custom_background.path
            else:
                bg_source = _get_preset_background(video.background_choice, temp_dir)
            if has_valid_replicate:
                current_img = _replace_background(current_img, bg_source, bg_applied_path)

        # 3. Generar Audio Neuronal desde el Guion
        asyncio.run(_generate_tts_audio(video.script_text, video.voice_id, audio_path))

        # 4. Generar Video Animado
        if has_valid_replicate:
            _animate_talking_head_cloud(current_img, audio_path, video.avatar.motion_style, final_video_path)
        else:
            _animate_local_fallback(
                current_img,
                audio_path,
                video.avatar.motion_style,
                video.avatar.motion_intensity,
                final_video_path
            )

            # 1. Convertir a Caricatura
        if video.avatar.visual_style != 'original':
            if has_valid_replicate:
                current_img = _stylize_to_cartoon(current_img, video.avatar.visual_style, cartoon_img_path)
                time.sleep(12)  # Pausa para respetar el límite de Replicate sin tarjeta
            else:
                current_img = _stylize_local_cartoon(current_img, video.avatar.visual_style, cartoon_img_path)

        # 2. Cambiar el Fondo
        if video.background_choice != 'original':
            if video.background_choice == 'custom' and video.custom_background:
                bg_source = video.custom_background.path
            else:
                bg_source = _get_preset_background(video.background_choice, temp_dir)
            if has_valid_replicate:
                current_img = _replace_background(current_img, bg_source, bg_applied_path)
                time.sleep(12)  # Pausa antes de llamar al modelo de animación de video

        # 3. Generar Audio Neuronal desde el Guion
        asyncio.run(_generate_tts_audio(video.script_text, video.voice_id, audio_path))

        # 4. Generar Video Animado
        if has_valid_replicate:
            _animate_talking_head_cloud(current_img, audio_path, video.avatar.motion_style, final_video_path)


def start_video_job_async(video_id: int):
    thread = threading.Thread(target=process_video_generation, args=(video_id,), daemon=True)
    thread.start()

    from PIL import Image, ImageDraw, ImageFilter, ImageOps

def _stylize_local_cartoon(image_path: str, style: str, output_path: str) -> str:
    """Efecto de ilustración / caricatura local usando Pillow cuando no hay API externa."""
    if style == 'original':
        return image_path
    img = Image.open(image_path).convert("RGB")
    # Suavizado de piel + realce de bordes tipo ilustración
    smooth = img.filter(ImageFilter.SMOOTH_MORE).filter(ImageFilter.SMOOTH_MORE)
    cartoon = ImageOps.posterize(smooth, bits=5 if style == 'cartoon_3d' else 4)
    cartoon.save(output_path, format="JPEG", quality=95)
    return output_path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

def _fix_image_orientation(image_path: str, temp_dir: str) -> str:
    """Corrige la rotación EXIF de fotos tomadas con celular para que no salgan acostadas."""
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    fixed_path = os.path.join(temp_dir, f"oriented_{os.path.basename(image_path)}")
    img.save(fixed_path, format="JPEG", quality=95)
    return fixed_path