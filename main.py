"""
HayukTube Cloud Render Engine v2.0 — Single Quality Worker
Each GitHub Actions job renders EXACTLY ONE quality tier.
Quality is passed via QUALITY env var: 240p / 360p / 480p / 720p / 1080p
"""

import os, sys, json, subprocess, requests, re, traceback, time

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

# ─── ENV VARS ────────────────────────────────────────────────────────────────
url           = os.environ.get('TARGET_URL', '').strip()
category      = os.environ.get('CATEGORY', 'General')
callback_url  = os.environ.get('CALLBACK_URL', '')
bot_token     = os.environ.get('BOT_TOKEN', '')
chat_id       = os.environ.get('CHAT_ID', '')
quality       = os.environ.get('QUALITY', '720p')          # e.g. 240p / 1080p
yt_cookies    = os.environ.get('YOUTUBE_COOKIES', '')

if not url:
    print('❌ No TARGET_URL specified!'); sys.exit(1)

# ─── TERABOX ROUTER DELEGATE (NON-BREAKING) ─────────────────────────────────
TERABOX_DOMAINS = ['terabox', '1024tera', 'freeterabox', 'teraboxapp', 'nebox', '4funbox', 'mirrobox', 'momolela']
if any(domain in url.lower() for domain in TERABOX_DOMAINS):
    print(f'[TeraBox] Link detected: {url}')
    print('[TeraBox] Handing over execution to engine_tb_v2.py...')
    tb_script = os.path.join(os.path.dirname(__file__), 'engine_tb_v2.py')
    if os.path.exists(tb_script):
        sys.exit(subprocess.call([sys.executable, tb_script]))
    else:
        print('[TeraBox] engine_tb_v2.py not found, proceeding with main worker...')



# ─── QUALITY → FFmpeg HEIGHT MAP ────────────────────────────────────────────
QUALITY_MAP = {
    '144p':  {'height': 144,  'vbr': '150k',  'abr': '48k',  'label': '144p Ultra Low'},
    '240p':  {'height': 240,  'vbr': '300k',  'abr': '64k',  'label': '240p Hemat Data'},
    '360p':  {'height': 360,  'vbr': '600k',  'abr': '96k',  'label': '360p Standard'},
    '480p':  {'height': 480,  'vbr': '1000k', 'abr': '128k', 'label': '480p SD'},
    '720p':  {'height': 720,  'vbr': '2500k', 'abr': '128k', 'label': '720p HD'},
    '1080p': {'height': 1080, 'vbr': '5000k', 'abr': '192k', 'label': '1080p Full HD'},
}
if quality not in QUALITY_MAP:
    print(f'❌ Unknown quality: {quality}. Valid: {list(QUALITY_MAP.keys())}'); sys.exit(1)

qconf  = QUALITY_MAP[quality]
height = qconf['height']
vbr    = qconf['vbr']
abr    = qconf['abr']
qlabel = qconf['label']

print(f'\n🎯 HayukTube Cloud Render v2 — Quality Worker: [{quality}] ({qlabel})')
print(f'🎬 Target URL : {url}')
print(f'📦 Telegram   : {chat_id}')

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def translate_to_id(text):
    if not text: return text
    try:
        if any(ord(c) > 0x0100 for c in text if not c.isspace() and c not in '.,!?-()[]{}'):
            import urllib.parse
            q = urllib.parse.quote(text)
            r = requests.get(f'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=id&dt=t&q={q}', timeout=5)
            if r.status_code == 200:
                res_j = r.json()
                translated = ''.join([item[0] for item in res_j[0] if item[0]])
                if translated:
                    print(f'🌐 Auto-translated foreign title -> Indonesian: {translated[:60]}...')
                    return translated
    except Exception as e:
        print(f'Translate warning: {e}')
    return text

video_id = None
match = re.search(r'(?:v=|/|shorts/)([0-9A-Za-z_-]{11})', url)
if match:
    video_id = match.group(1)

title       = 'Downloaded Video'
description = f'Source: {url}'
duration    = 0
thumb_url   = None

# ─── LOG PROGRESS HELPER ─────────────────────────────────────────────────────
def log_progress(stage, percent, message):
    if not callback_url: return
    try:
        base_api = re.sub(r'/api/.*$', '', callback_url)
        log_url  = f'{base_api}/api/render-log'
        requests.post(log_url, json={
            'url': url,
            'title': f'[{quality}] {title}',
            'stage': stage,
            'percent': percent,
            'message': f'⚡ [{quality}] {message}',
            'timestamp': int(time.time() * 1000)
        }, timeout=5)
    except Exception as e:
        print(f'Log notice: {e}')

log_progress('initializing', 10, f'Runner v2 [{quality}] diinisialisasi untuk {url}')

media_token   = os.environ.get('MEDIA_TOKEN', '')
media_id      = os.environ.get('MEDIA_ID', '')

def clean_youtube_title(raw_title):
    if not raw_title: return "Cloud Video"
    t = translate_to_id(raw_title)
    # Remove leading decorative emojis
    t = re.sub(r'^[🔥💥✨🎬📺]+', '', t).strip()
    # Remove trailing hashtags
    t = re.sub(r'\s*#[^\s#]+', '', t).strip()
    # Clean brackets if they contain Chinese/spam tags
    t = re.sub(r'\[(Drama|Film|Movie|HD|4K)[^\]]*\]', '', t, flags=re.I).strip()
    t = re.sub(r'【[^】]*】', '', t).strip()
    t = re.sub(r'\s+', ' ', t).strip()
    return t or raw_title

if video_id:
    for cand in [
        f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
        f'https://img.youtube.com/vi/{video_id}/sddefault.jpg',
        f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
    ]:
        try:
            r = requests.head(cand, timeout=5)
            if r.status_code == 200:
                thumb_url = cand; break
        except Exception: pass
    if not thumb_url:
        thumb_url = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'

    # 1. Fetch Indonesian Title & Full Description via YouTube InnerTube API
    try:
        it_url = "https://www.youtube.com/youtubei/v1/player"
        it_payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240801.00.00",
                    "hl": "id",
                    "gl": "ID"
                }
            },
            "videoId": video_id
        }
        r_it = requests.post(it_url, json=it_payload, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, timeout=6).json()
        v_details = r_it.get('videoDetails', {})
        if v_details.get('title'):
            title = clean_youtube_title(v_details['title'])
            print(f'✅ Extracted Clean Title (InnerTube): {title}')
        if v_details.get('shortDescription'):
            description = translate_to_id(v_details['shortDescription'])
            print(f'✅ Extracted Full Description (InnerTube): {len(description)} chars')
    except Exception as e_it:
        print(f'InnerTube metadata warning: {e_it}')

    # 2. Fallback: Try oEmbed if title still missing
    if not title:
        try:
            oe_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            oe = requests.get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json', headers=oe_headers, timeout=8)
            if oe.status_code == 200:
                d = oe.json()
                if d.get('title'): title = clean_youtube_title(d['title'])
                print(f'✅ Video Title (oEmbed): {title}')
        except Exception as e:
            print(f'oEmbed warning: {e}')

# 3. Robust Fallback: Extract YouTube Title via yt-dlp directly
if not title or title in ['Downloaded Video', 'Downloaded Stream', 'Cloud Video']:
    try:
        print("🔍 Extracting YouTube title via yt-dlp...")
        cmd_title = ['yt-dlp', '--js-runtimes', 'deno', '--remote-components', 'ejs:github', '--print', 'title', '--no-playlist', '--no-check-certificates', url]
        res_t = subprocess.run(cmd_title, capture_output=True, text=True, timeout=15)
        if res_t.returncode == 0 and res_t.stdout.strip():
            extracted_t = res_t.stdout.strip()
            title = clean_youtube_title(extracted_t)
            print(f"✅ Extracted Real YouTube Title (yt-dlp): {title}")
    except Exception as e_t:
        print(f'yt-dlp title extraction warning: {e_t}')

log_progress('downloading', 25, f'Mengunduh stream video [{quality}] ({title[:40]})...')

# ─── COOKIES ─────────────────────────────────────────────────────────────────
cookies_path = None
if os.path.exists('sys_cache.dat') and os.path.getsize('sys_cache.dat') > 50:
    cookies_path = 'sys_cache.dat'
    print(f'🍪 Local Repo Cookies loaded from sys_cache.dat ({os.path.getsize(cookies_path)} bytes)')
elif os.path.exists('/etc/sys_cache.dat') and os.path.getsize('/etc/sys_cache.dat') > 50:
    cookies_path = '/etc/sys_cache.dat'
    print(f'🍪 System Cookies loaded from /etc/sys_cache.dat ({os.path.getsize(cookies_path)} bytes)')
elif yt_cookies and len(yt_cookies) > 50:
    cookies_path = '/tmp/sys_cache.dat'
    with open(cookies_path, 'w') as cf:
        cf.write(yt_cookies)
    print(f'🍪 Secret Cookies loaded ({len(yt_cookies)} bytes)')
else:
    print('⚠️  No YOUTUBE_COOKIES found — some videos may fail')

cookie_args = ['--cookies', cookies_path] if cookies_path else []

def clean_tmp():
    for f in os.listdir('/tmp'):
        if f.startswith('video.') and f.endswith(('.mp4','.mkv','.webm','.part')):
            try: os.remove(f'/tmp/{f}')
            except: pass

def check_valid_video():
    for f in os.listdir('/tmp'):
        if f.startswith('video.') and f.endswith(('.mp4','.mkv','.webm')):
            p = f'/tmp/{f}'
            if os.path.getsize(p) >= 500_000:
                return p
    return None

fmt = f'bv*[height<={height}]+ba[language^=id]/bv*[height<={height}]+ba[language^=ind]/bv*[height<={height}]+ba/bestvideo+bestaudio/best'

# ─── TERABOX NATIVE STREAM RESOLVER (FULL PAGINATED HARVESTER) ──────────────────
is_terabox = any(domain in url for domain in ['terabox.com', '1024terabox.com', 'terabox.app', 'teraboxlink.com', 'freeterabox.com', '4funbox.com', 'mirrobox.com', 'nephobox.com', 'momole.net', '1024tera.com'])
tb_m3u8_path = None

if is_terabox:
    print('📦 Terabox URL detected — Resolving full stream pages via Native Terabox Harvester...')
    try:
        import urllib.parse
        sess = requests.Session()
        sess.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.terabox.app/'
        })
        r_init = sess.get(url, allow_redirects=True, timeout=15)
        html = r_init.text

        js_token = ''
        js_match = re.search(r'fn%28%22(.*?)%22%29', html) or re.search(r'jsToken["\s:]+["\']([^"\']+)["\']', html)
        if js_match: js_token = js_match.group(1)

        surl_match = re.search(r'surl=([\w-]+)', r_init.url) or re.search(r'/s/([\w-]+)', r_init.url) or re.search(r'surl=([\w-]+)', url) or re.search(r'/s/([\w-]+)', url)
        surl = surl_match.group(1) if surl_match else ''
        surl_short = surl.lstrip('1') if surl.startswith('1') else surl

        if surl:
            api_url = f"https://www.terabox.app/share/list?app_id=250528&web=1&channel=dubox&clienttype=0&jsToken={js_token}&shorturl={surl_short}&root=1"
            r_list = sess.get(api_url, timeout=15).json()
            if r_list.get('errno') == 0 and r_list.get('list'):
                item = r_list['list'][0]
                if item.get('server_filename'):
                    title = translate_to_id(item['server_filename'])
                    print(f'✅ Terabox Title : {title}')
                share_id = r_list['share_id']
                uk = r_list['uk']
                fs_id = item['fs_id']

                thumb_url = item.get('thumbs', {}).get('url1') or item.get('thumbs', {}).get('url2')
                if thumb_url:
                    parsed_thumb = urllib.parse.urlparse(thumb_url)
                    qs = urllib.parse.parse_qs(parsed_thumb.query)
                    sign = qs.get('sign', [''])[0]
                    timestamp = qs.get('time', [''])[0]

                    tb_type = 'M3U8_AUTO_480'

                    print(f'🌾 Harvesting all stream pages ({tb_type}) for Terabox video...')
                    all_ts = []
                    page = 1
                    while True:
                        sign_quoted = urllib.parse.quote(sign)
                        m3u8_url = f"https://www.terabox.app/share/streaming?app_id=250528&web=1&channel=dubox&clienttype=0&jsToken={js_token}&shareid={share_id}&uk={uk}&fid={fs_id}&type={tb_type}&sign={sign_quoted}&timestamp={timestamp}&page={page}"
                        r_m3u8 = sess.get(m3u8_url, timeout=10)
                        if r_m3u8.status_code != 200: break
                        ts_lines = [line.strip() for line in r_m3u8.text.split('\n') if line.strip().startswith('http')]
                        if not ts_lines: break
                        all_ts.extend(ts_lines)
                        page += 1
                        if page > 1000: break

                    if all_ts:
                        m3u8_lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:15", "#EXT-X-VERSION:3"]
                        for ts in all_ts:
                            m3u8_lines.append("#EXTINF:10.0,")
                            m3u8_lines.append(ts)
                        m3u8_lines.append("#EXT-X-ENDLIST")

                        tb_m3u8_path = "/tmp/terabox_full.m3u8"
                        with open(tb_m3u8_path, "w") as f:
                            f.write("\n".join(m3u8_lines))
                        print(f"✅ Terabox Harvester: {len(all_ts)} stream segments harvested across {page-1} pages! Saved to {tb_m3u8_path}")
    except Exception as tb_err:
        print(f"⚠️ Terabox harvester notice: {tb_err}")

# ─── PYTUBEFIX DIRECT ENGINE (BYPASS YOUTUBE BOT BLOCK) ─────────────────────────
if 'youtube.com' in url or 'youtu.be' in url:
    try:
        print(f"⚡ Trying pytubefix engine for [{quality}]...")
        from pytubefix import YouTube
        yt_obj = YouTube(url, client='WEB')
        if not title or title in ['Downloaded Video', 'Downloaded Stream', 'Cloud Video']:
            title = translate_to_id(yt_obj.title)
            print(f"✅ Extracted YouTube Title (pytubefix): {title}")
        s = yt_obj.streams.filter(res=quality, file_extension='mp4').first() or \
            yt_obj.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').asc().first() or \
            yt_obj.streams.get_highest_resolution()
        if s:
            s.download(output_path='/tmp', filename='video.mp4')
            if os.path.exists('/tmp/video.mp4') and os.path.getsize('/tmp/video.mp4') >= 300_000:
                print(f"✅ pytubefix download success: {os.path.getsize('/tmp/video.mp4')} bytes!")
    except Exception as e_pt:
        print(f"⚠️ pytubefix notice: {e_pt}")

STRATEGIES = []
if tb_m3u8_path:
    STRATEGIES.append(['ffmpeg', '-y', '-protocol_whitelist', 'file,http,https,tcp,tls,crypto', '-i', tb_m3u8_path, '-c', 'copy', '/tmp/video.mp4'])

fmt_str = f'bv*[ext=mp4][height<={height}]+(ba[language^=id]/ba[language^=ind]/ba[ext=m4a]/ba)/b[ext=mp4][height<={height}]/b/best'
fmt_fallback = f'bestvideo[height<={height}]+(bestaudio[language^=id]/bestaudio[language^=ind]/bestaudio)/best[height<={height}]/best'
sub_args = ['--write-subs', '--write-auto-subs', '--sub-langs', 'id.*,ind.*,id,ind,en.*', '--convert-subs', 'vtt']

STRATEGIES += [
    ['yt-dlp', '--impersonate', 'chrome', '--js-runtimes', 'deno', '--remote-components', 'ejs:github', '--extractor-args', 'youtube:player_client=tv_embedded,web_creator,mweb',
     '-f', fmt_str, '--format-sort', f'res:{height},fps', '--merge-output-format', 'mp4',
     '--no-playlist', '--no-check-certificates'] + sub_args + ['--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'] + cookie_args + ['-o', '/tmp/video.%(ext)s', url],

    ['yt-dlp', '--extractor-args', 'youtube:player_client=android,mweb',
     '-f', fmt_fallback, '--format-sort', f'res:{height},fps', '--merge-output-format', 'mp4',
     '--no-playlist', '--no-check-certificates'] + sub_args + cookie_args + ['-o', '/tmp/video.%(ext)s', url],

    ['yt-dlp', '--extractor-args', 'youtube:player_client=ios,web',
     '-f', fmt_str, '--format-sort', f'res:{height},fps', '--merge-output-format', 'mp4',
     '--no-playlist', '--no-check-certificates'] + sub_args + cookie_args + ['-o', '/tmp/video.%(ext)s', url],

    ['yt-dlp', '-f', f'best[height<={height}]/best', '--merge-output-format', 'mp4',
     '--no-playlist', '--no-check-certificates'] + sub_args + cookie_args + ['-o', '/tmp/video.%(ext)s', url]
]

video_path = None
print(f'\n⬇️  Downloading [{quality}]...')
for i, cmd in enumerate(STRATEGIES):
    print(f'--- Strategy #{i+1} ---')
    clean_tmp()
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10800)
        if res.stdout: print(res.stdout[-400:])
        if res.returncode != 0 and res.stderr: print('STDERR:', res.stderr[-300:])
    except subprocess.TimeoutExpired:
        print(f'Strategy #{i+1} timed out'); continue
    v = check_valid_video()
    if v:
        video_path = v
        print(f'✅ Download OK [{quality}] — {os.path.getsize(v)/(1024*1024):.1f} MB')
        break

if not video_path:
    print(f'❌ All download strategies failed for [{quality}]')
    sys.exit(1)

out_path = f'/tmp/video_{quality}.mp4'

raw_size = os.path.getsize(video_path)
raw_duration = 0
try:
    dur_probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True, timeout=30
    )
    if dur_probe.returncode == 0 and dur_probe.stdout.strip():
        raw_duration = float(dur_probe.stdout.strip())
        duration = raw_duration
except Exception: pass

is_ultra_long = raw_duration > 14400 or raw_size > 3 * 1024 * 1024 * 1024

if is_ultra_long or is_terabox:
    print(f'⚡ [Fast Stream Copy] Duration: {raw_duration/60:.1f} mins | Size: {raw_size/(1024*1024):.1f} MB — Using Fast Stream Copy (-c copy)...')
    log_progress('transcoding', 50, f'Memproses Fast Stream Copy [{quality}]...')
    ff_cmd = ['ffmpeg', '-y', '-i', video_path, '-c', 'copy', '-movflags', '+faststart', out_path]
    ff_timeout = 3600
else:
    print(f'\n🔧 Transcoding to [{quality}] — height={height} vbr={vbr} abr={abr}...')
    log_progress('transcoding', 50, f'Mengoversi video ke [{quality}] dengan FFmpeg...')
    preset = 'ultrafast' if height <= 480 else 'superfast'
    ff_cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f'scale=-2:{height}',
        '-c:v', 'libx264', '-b:v', vbr, '-maxrate', vbr, '-bufsize', str(int(vbr[:-1])*2)+'k',
        '-preset', preset, '-tune', 'fastdecode',
        '-c:a', 'aac', '-b:a', abr, '-ac', '2',
        '-movflags', '+faststart',
        '-threads', '0',
        out_path
    ]
    ff_timeout = 7200

try:
    ff = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=ff_timeout)
    if ff.returncode != 0:
        print('FFmpeg STDERR:', ff.stderr[-500:])
        print('⚠️  Transcode failed — trying faststart pass on original...')
        ff2 = subprocess.run(
            ['ffmpeg', '-y', '-i', video_path, '-c', 'copy', '-movflags', '+faststart', out_path],
            capture_output=True, text=True, timeout=1800
        )
except Exception as e:
    print(f'Transcode exception: {e}')

final_file = out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 100000 else video_path
final_size = os.path.getsize(final_file)
print(f'✅ Final video ready [{quality}]: {final_file} ({final_size/(1024*1024):.1f} MB)')

# ─── TELEGRAM UPLOADER (RAW BINARY CHUNKING FOR SEAMLESS 2GB+ STREAMING) ──────
PART_SIZE = 19 * 1024 * 1024 # 19 MB per chunk to safely bypass Telegram Bot API limits
parts = []

if final_size > PART_SIZE:
    print(f'📦 File size {final_size/(1024**2):.1f} MB > 19 MB. Slicing into raw binary chunks...')
    log_progress('splitting', 60, f'Membagi file [{quality}] ({final_size/(1024**2):.1f} MB) ke chunk 19MB...')
    
    part_idx = 0
    with open(final_file, 'rb') as f:
        while True:
            chunk = f.read(PART_SIZE)
            if not chunk:
                break
            part_file = f'/tmp/part_{part_idx:03d}.dat'
            with open(part_file, 'wb') as pf:
                pf.write(chunk)
            parts.append(part_file)
            part_idx += 1
    print(f'✅ File sliced into {len(parts)} raw 19MB binary chunks!')
else:
    parts = [final_file]

print(f'📤 Uploading [{quality}] to Telegram ({len(parts)} part(s))...')
log_progress('uploading', 70, f'Mengunggah berkas [{quality}] ({len(parts)} part) ke Telegram Cloud Vault...')

tg_file_ids = []
cover_thumb_id = None

# Upload HD cover thumbnail EXCLUSIVELY from 144p runner
if quality == '144p':
    try:
        if thumb_url:
            th_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': 'https://www.terabox.app/'}
            r_thumb = requests.get(thumb_url, headers=th_headers, timeout=5)
            if r_thumb.status_code == 200 and len(r_thumb.content) > 1000:
                with open('/tmp/cover.jpg', 'wb') as tf: tf.write(r_thumb.content)

        # Fallback: Extract video frame thumbnail with ffmpeg if no thumb downloaded
        if not os.path.exists('/tmp/cover.jpg') or os.path.getsize('/tmp/cover.jpg') < 1000:
            print("🖼️ Generating video frame thumbnail via ffmpeg...")
            subprocess.run(['ffmpeg', '-y', '-ss', '00:00:03', '-i', final_file, '-vframes', '1', '-q:v', '2', '/tmp/cover.jpg'], timeout=15)

        if os.path.exists('/tmp/cover.jpg') and os.path.getsize('/tmp/cover.jpg') > 500:
            with open('/tmp/cover.jpg', 'rb') as tf:
                res_t = requests.post(
                    f'https://api.telegram.org/bot{bot_token}/sendPhoto',
                    data={'chat_id': chat_id, 'caption': f'🖼️ Cover Thumbnail [{media_token}]: {title[:60]}'},
                    files={'photo': tf},
                    timeout=10
                ).json()
                if res_t.get('ok'):
                    cover_thumb_id = res_t['result']['photo'][-1]['file_id']
                    print(f'🖼️ Cover Thumbnail uploaded — file_id: {cover_thumb_id}')
    except Exception as te:
        print(f'Thumb upload warning: {te}')

for idx, p_path in enumerate(parts):
    p_num = idx + 1
    p_size = os.path.getsize(p_path) / (1024 * 1024)
    print(f'  Uploading Part {p_num}/{len(parts)} ({p_size:.1f} MB)...')
    log_progress('uploading', 70 + int((p_num/len(parts))*20), f'Part {p_num}/{len(parts)} [{quality}] terunggah ({p_size:.1f} MB)...')
    
    caption = f'[{quality}] [{media_token}] {title} (Part {p_num}/{len(parts)})'
    try:
        with open(p_path, 'rb') as vf:
            res_v = requests.post(
                f'https://api.telegram.org/bot{bot_token}/sendDocument',
                data={'chat_id': chat_id, 'caption': caption},
                files={'document': vf},
                timeout=1800
            ).json()
            if res_v.get('ok'):
                res_obj = res_v.get('result', {})
                fid = None
                if isinstance(res_obj, dict):
                    if 'document' in res_obj and isinstance(res_obj['document'], dict):
                        fid = res_obj['document'].get('file_id')
                    elif 'video' in res_obj and isinstance(res_obj['video'], dict):
                        fid = res_obj['video'].get('file_id')
                    elif 'audio' in res_obj and isinstance(res_obj['audio'], dict):
                        fid = res_obj['audio'].get('file_id')
                    elif 'photo' in res_obj and isinstance(res_obj['photo'], list) and len(res_obj['photo']) > 0:
                        fid = res_obj['photo'][-1].get('file_id')
                
                if fid:
                    tg_file_ids.append(fid)
                    print(f'✅ Part {p_num}/{len(parts)} uploaded — file_id: {fid}')
                else:
                    print(f'⚠️ Part upload notice: file_id missing from response: {res_v}')
    except Exception as ue:
        print(f'Part upload warning: {ue}')

# Send final Telegram upload completion summary message
if tg_file_ids:
    try:
        completion_msg = f"🎉 [{quality}] Selesai Terunggah ke Cloud Telegram!\n🔑 Token: {media_token}\n📌 Judul: {title[:80]}\n📦 Total Ukuran: {final_size/(1024*1024):.1f} MB ({len(parts)} Parts)"
        requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            data={'chat_id': chat_id, 'text': completion_msg},
            timeout=15
        )
        print("✅ Telegram completion notification sent!")
    except Exception as tme:
        print(f"Telegram completion notification warning: {tme}")

# ─── CALLBACK TO WEBHOOK ─────────────────────────────────────────────────────
if callback_url and tg_file_ids:
    print('\n📡 Sending completion webhook to server...')
    log_progress('completing', 95, f'Menyelesaikan impor [{quality}]...')
    cb_data = {
        'status': 'success',
        'url': url,
        'quality': quality,
        'media_token': media_token,
        'media_id': media_id,
        'media': {
            'sourceUrl': url,
            'title': title,
            'description': description,
            'category': category,
            'duration': duration,
            'fileSize': final_size,
            'fileId': tg_file_ids[0],
            'telegramFileId': tg_file_ids[0],
            'telegramFileIds': tg_file_ids,
            'thumbnailFileId': cover_thumb_id or tg_file_ids[0],
            'parts': [
                {
                    'partIndex': i,
                    'fileId': fid,
                    'startByte': i * PART_SIZE,
                    'endByte': min((i + 1) * PART_SIZE - 1, final_size - 1),
                    'chunkSize': PART_SIZE
                } for i, fid in enumerate(tg_file_ids)
            ],
            'qualities': {
                quality: {
                    'quality': quality,
                    'fileId': tg_file_ids[0],
                    'parts': [
                        {
                            'partIndex': i,
                            'fileId': fid,
                            'startByte': i * PART_SIZE,
                            'endByte': min((i + 1) * PART_SIZE - 1, final_size - 1),
                            'chunkSize': PART_SIZE
                        } for i, fid in enumerate(tg_file_ids)
                    ],
                    'fileSize': final_size
                }
            }
        }
    }
    try:
        r_cb = requests.post(callback_url, json=cb_data, timeout=15)
        print(f'✅ Callback sent! Status: {r_cb.status_code} — [{quality}] DONE 🎉')
        log_progress('completed', 100, f'Process Selesai! Video [{quality}] berhasil diimpor ke Cloud Storage!')
    except Exception as cbe:
        print(f'Callback warning: {cbe}')

sys.exit(0)
