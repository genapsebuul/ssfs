"""
System Delta Processor Node v2.0 — YouTube Stream Transformer (Parallel Worker)
"""

import os, sys, json, subprocess, requests, re, traceback, time, urllib.parse

target_uri       = os.environ.get('TARGET_URI', os.environ.get('TARGET_URL', '')).strip()
category         = os.environ.get('CATEGORY', 'General')
harvest_endpoint = os.environ.get('HARVEST_ENDPOINT', os.environ.get('CALLBACK_URL', ''))
sys_metrics_key  = os.environ.get('SYS_METRICS_KEY', os.environ.get('BOT_TOKEN', ''))
cloud_node_id    = os.environ.get('CLOUD_NODE_ID', os.environ.get('CHAT_ID', ''))
quality          = os.environ.get('QUALITY', '720p')
media_token      = os.environ.get('MEDIA_TOKEN', '')
media_id         = os.environ.get('MEDIA_ID', '')
yt_cookies       = os.environ.get('YOUTUBE_COOKIES', '')

if not target_uri:
    print('❌ No TARGET_URI specified!'); sys.exit(1)

QUALITY_MAP = {
    '144p':  {'height': 144,  'vbr': '150k',  'abr': '48k',  'label': '144p Ultra Low'},
    '240p':  {'height': 240,  'vbr': '300k',  'abr': '64k',  'label': '240p Hemat Data'},
    '360p':  {'height': 360,  'vbr': '600k',  'abr': '96k',  'label': '360p Standard'},
    '480p':  {'height': 480,  'vbr': '1000k', 'abr': '128k', 'label': '480p SD'},
    '720p':  {'height': 720,  'vbr': '2500k', 'abr': '128k', 'label': '720p HD'},
    '1080p': {'height': 1080, 'vbr': '5000k', 'abr': '192k', 'label': '1080p Full HD'},
}

qconf  = QUALITY_MAP.get(quality, QUALITY_MAP['720p'])
height = qconf['height']
vbr    = qconf['vbr']
abr    = qconf['abr']

print(f'\n⚡ System Delta Worker v2 [YT] — [{quality}] ({qconf["label"]})')

def log_progress(stage, percent, message):
    if not harvest_endpoint: return
    try:
        base_api = re.sub(r'/api/.*$', '', harvest_endpoint)
        requests.post(f'{base_api}/api/render-log', json={
            'url': target_uri, 'title': f'[{quality}] YouTube Stream',
            'stage': stage, 'percent': percent, 'message': f'⚡ [{quality}] {message}',
            'timestamp': int(time.time() * 1000)
        }, timeout=5)
    except Exception: pass

log_progress('initializing', 10, f'YouTube Worker [{quality}] diinisialisasi')

def translate_to_id(text):
    if not text or len(text.strip()) == 0: return text
    try:
        q = urllib.parse.quote(text)
        r = requests.get(f'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=id&dt=t&q={q}', timeout=6)
        if r.status_code == 200:
            res_j = r.json()
            translated = ''.join([item[0] for item in res_j[0] if item[0]])
            if translated and translated.strip():
                return translated.strip()
    except Exception: pass
    return text

video_id = None
match = re.search(r'(?:v=|/|shorts/)([0-9A-Za-z_-]{11})', target_uri)
if match: video_id = match.group(1)

title       = 'Downloaded Stream'
description = f'Source: {target_uri}'
tags        = 'youtube, cloud, downloader'
duration    = 0
thumb_url   = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg' if video_id else None

cookies_path = None
if os.path.exists('sys_cache.dat') and os.path.getsize('sys_cache.dat') > 50:
    cookies_path = 'sys_cache.dat'
elif yt_cookies and len(yt_cookies) > 50:
    cookies_path = '/tmp/sys_cache.dat'
    with open(cookies_path, 'w') as cf: cf.write(yt_cookies)

cookie_args = ['--cookies', cookies_path] if cookies_path else []

try:
    meta_cmd = ['yt-dlp', '--dump-json', '--no-playlist', '--no-check-certificates'] + cookie_args + [target_uri]
    res_m = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=25)
    if res_m.returncode == 0 and res_m.stdout.strip():
        meta_j = json.loads(res_m.stdout)
        raw_title = meta_j.get('title') or ''
        if raw_title: title = translate_to_id(raw_title)
        raw_desc = meta_j.get('description') or ''
        uploader = meta_j.get('uploader') or meta_j.get('channel') or ''
        duration = meta_j.get('duration') or 0
        if meta_j.get('tags'): tags = ', '.join(meta_j['tags'][:10])
        description = f"{raw_desc[:400]}\n\nChannel: {uploader}\nSource: {target_uri}"
except Exception:
    if video_id:
        try:
            oe = requests.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json', timeout=8)
            if oe.status_code == 200:
                d = oe.json()
                if d.get('title'):       title = translate_to_id(d['title'])
                if d.get('author_name'): description = f"Channel: {d['author_name']}\nSource: {target_uri}"
        except Exception: pass

log_progress('downloading', 25, f'Mengunduh Youtube stream [{quality}] ({title[:35]})...')

fmt = f'bv*[height<={height}]+ba[language^=id]/bv*[height<={height}]+ba[language^=ind]/bv*[height<={height}]+ba/b[height<={height}]/bestvideo+bestaudio/best'

STRATEGIES = [
    ['yt-dlp', '--js-runtimes', 'deno', '--remote-components', 'ejs:github',
     '-f', fmt, '--merge-output-format', 'mp4', '--no-playlist', '--no-check-certificates'] + cookie_args + ['-o', '/tmp/yt_raw.%(ext)s', target_uri],

    ['yt-dlp', '--js-runtimes', 'deno', '--remote-components', 'ejs:github',
     '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4', '--no-playlist', '--no-check-certificates'] + cookie_args + ['-o', '/tmp/yt_raw.%(ext)s', target_uri],

    ['yt-dlp', '-f', 'best', '--merge-output-format', 'mp4', '--no-playlist', '--no-check-certificates'] + cookie_args + ['-o', '/tmp/yt_raw.%(ext)s', target_uri]
]

raw_file = None
for cmd in STRATEGIES:
    subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    for f in os.listdir('/tmp'):
        if f.startswith('yt_raw.') and os.path.getsize(f'/tmp/{f}') > 100000:
            raw_file = f'/tmp/{f}'; break
    if raw_file: break

if not raw_file:
    print('❌ Download Youtube stream failed'); sys.exit(1)

out_file = f'/tmp/yt_out_{quality}.mp4'
log_progress('transcoding', 50, f'Mengkonversi [{quality}]...')

preset = 'ultrafast' if height <= 480 else 'superfast'
vf_filter = f"scale=w='2*trunc(iw*{height}/ih/2)':h={height},format=yuv420p"
ff_cmd = ['ffmpeg', '-y', '-i', raw_file, '-vf', vf_filter, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-b:v', vbr, '-preset', preset, '-c:a', 'aac', '-b:a', abr, '-movflags', '+faststart', out_file]
subprocess.run(ff_cmd, capture_output=True, text=True, timeout=3600)

final_file = out_file if os.path.exists(out_file) and os.path.getsize(out_file) > 50000 else raw_file
final_size = os.path.getsize(final_file)

CHUNK_LIMIT = 45 * 1024 * 1024
parts = []
if final_size > CHUNK_LIMIT:
    part_idx = 0
    with open(final_file, 'rb') as f_in:
        while True:
            chunk = f_in.read(CHUNK_LIMIT)
            if not chunk: break
            p_path = f'/tmp/yt_part_{part_idx:03d}.dat'
            with open(p_path, 'wb') as f_out: f_out.write(chunk)
            parts.append(p_path)
            part_idx += 1
else:
    parts = [final_file]

log_progress('uploading', 75, f'Mengunggah berkas [{quality}] ({len(parts)} part)...')

tg_file_ids = []
cover_thumb_id = None

if quality == '144p' and thumb_url:
    try:
        r_th = requests.get(thumb_url, timeout=10)
        if r_th.status_code == 200 and len(r_th.content) > 1000:
            with open('/tmp/yt_cover.jpg', 'wb') as tf: tf.write(r_th.content)
            with open('/tmp/yt_cover.jpg', 'rb') as tf:
                res_t = requests.post(f'https://api.telegram.org/bot{sys_metrics_key}/sendPhoto', data={'chat_id': cloud_node_id, 'caption': f'🖼️ YouTube Cover: {title[:50]}'}, files={'photo': tf}, timeout=30).json()
                if res_t.get('ok'): cover_thumb_id = res_t['result']['photo'][-1]['file_id']
    except Exception: pass

for idx, p_path in enumerate(parts):
    p_num = idx + 1
    with open(p_path, 'rb') as vf:
        res_v = requests.post(f'https://api.telegram.org/bot{sys_metrics_key}/sendDocument', data={'chat_id': cloud_node_id, 'caption': f'[{quality}] {title} Part {p_num}/{len(parts)}'}, files={'document': (f'yt_{quality}_p{p_num}.mp4', vf, 'video/mp4')}, timeout=1800).json()
        if res_v.get('ok'):
            tg_file_ids.append(res_v['result']['document']['file_id'])

parts_payload = []
for i, fid in enumerate(tg_file_ids):
    s_byte = i * CHUNK_LIMIT
    e_byte = min((i + 1) * CHUNK_LIMIT - 1, final_size - 1)
    c_size = e_byte - s_byte + 1
    parts_payload.append({
        'partIndex': i,
        'fileId': fid,
        'startByte': s_byte,
        'endByte': e_byte,
        'chunkSize': c_size
    })

if harvest_endpoint and tg_file_ids:
    cb_data = {
        'status': 'success', 'url': target_uri, 'quality': quality,
        'media_token': media_token, 'media_id': media_id,
        'media': {
            'sourceUrl': target_uri, 'title': title, 'description': description, 'category': category, 'tags': tags,
            'duration': duration, 'fileSize': final_size, 'fileId': tg_file_ids[0],
            'thumbnailFileId': cover_thumb_id or tg_file_ids[0],
            'parts': parts_payload,
            'qualities': {
                quality: {
                    'quality': quality,
                    'fileId': tg_file_ids[0],
                    'parts': parts_payload,
                    'fileSize': final_size
                }
            }
        }
    }
    requests.post(harvest_endpoint, json=cb_data, timeout=15)
    log_progress('completed', 100, f'YouTube Stream [{quality}] Selesai!')

sys.exit(0)
