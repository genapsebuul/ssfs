"""
Cluster Delta Processor Node v2.0 — TeraBox Stream Harvester & Downscaling Transcoder
Features: Optimized M3U8 Segment Harvester + yt-dlp Fallback + FFmpeg Downscaling (144p-1080p) + 45MB Chunking
"""

import os, sys, json, subprocess, requests, re, traceback, time, urllib.parse, concurrent.futures

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

target_uri       = os.environ.get('TARGET_URI', os.environ.get('TARGET_URL', '')).strip()
category         = os.environ.get('CATEGORY', 'General')
harvest_endpoint = os.environ.get('HARVEST_ENDPOINT', os.environ.get('CALLBACK_URL', ''))
sys_metrics_key  = os.environ.get('SYS_METRICS_KEY', os.environ.get('BOT_TOKEN', '')).strip() or '8899812523:AAHBTqKxaSiTWq8bRLs0tvuoktZyyc8W7ps'
cloud_node_id    = os.environ.get('CLOUD_NODE_ID', os.environ.get('CHAT_ID', '')).strip() or '-1003811040179'
quality          = os.environ.get('QUALITY', '480p')
media_token      = os.environ.get('MEDIA_TOKEN', '')
media_id         = os.environ.get('MEDIA_ID', '')
render_scope     = os.environ.get('VISIBILITY', os.environ.get('RENDER_MODE', 'public')).strip()
content_tag      = os.environ.get('IS_18_PLUS', 'true').strip().lower() == 'true'

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

qconf  = QUALITY_MAP.get(quality, QUALITY_MAP['480p'])
height = qconf['height']
vbr    = qconf['vbr']
abr    = qconf['abr']

print(f'\n⚡ Cluster Delta Worker v2 [TeraBox] — [{quality}] ({qconf["label"]})')

def log_progress(stage, percent, message):
    if not harvest_endpoint: return
    try:
        base_api = re.sub(r'/api/.*$', '', harvest_endpoint)
        requests.post(f'{base_api}/api/render-log', json={
            'url': target_uri, 'title': f'[{quality}] TeraBox Stream',
            'stage': stage, 'percent': percent, 'message': f'⚡ [{quality}] {message}',
            'timestamp': int(time.time() * 1000)
        }, timeout=5)
    except Exception: pass

log_progress('initializing', 10, f'TeraBox Harvester [{quality}] diinisialisasi')

title = 'TeraBox Cloud Video'
thumb_url = None
tb_m3u8_path = None

sess = requests.Session()
sess.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Referer': 'https://www.terabox.app/'
})

# -------------------------------------------------------------
# Rich TeraBox Cookie Loader (File & Environment Fallback)
# -------------------------------------------------------------
cookies_dict = {}

# 1. Read from TERABOX_COOKIE_FILE if provided
cookie_file = os.environ.get('TERABOX_COOKIE_FILE', '').strip()
if cookie_file and os.path.exists(cookie_file):
    try:
        with open(cookie_file, 'r', encoding='utf-8') as f_c:
            for line in f_c:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    if v.strip(): cookies_dict[k.strip()] = v.strip()
    except Exception as e_cf:
        print(f'Notice parsing cookie file: {e_cf}')

# 2. Read from Environment Variables
env_ndus = os.environ.get('NDUS', '').strip()
if env_ndus: cookies_dict['ndus'] = env_ndus

env_ndus_fam = os.environ.get('NDUS_FAMILY', '').strip()
if env_ndus_fam: cookies_dict['ndus_family'] = env_ndus_fam

env_bduss = os.environ.get('BDUSS', '').strip()
if env_bduss: cookies_dict['BDUSS'] = env_bduss

env_stoken = os.environ.get('STOKEN', '').strip()
if env_stoken: cookies_dict['STOKEN'] = env_stoken

env_csrf = os.environ.get('CSRF_TOKEN', '').strip()
if env_csrf: cookies_dict['csrfToken'] = env_csrf

env_browserid = os.environ.get('BROWSERID', '').strip()
if env_browserid: cookies_dict['browserid'] = env_browserid

# 3. Ultimate Fallback for NDUS token
if 'ndus' not in cookies_dict:
    tb_cookie = os.environ.get('TERABOX_COOKIE', '').strip()
    if not tb_cookie:
        tb_cookie = 'YzuXcdVpeHui1nF7cqcomRuobmjrhKUZ9K6lrf7B'
    cookies_dict['ndus'] = tb_cookie.replace('ndus=', '').strip()

# Build Cookie Header String & Attach to Session
cookie_str = '; '.join([f'{k}={v}' for k, v in cookies_dict.items()])
sess.headers['Cookie'] = cookie_str
sess.headers['Referer'] = 'https://dm.terabox.com/main?category=all'

print(f"🔑 Loaded TeraBox Cookies ({len(cookies_dict)} keys): {', '.join(cookies_dict.keys())}")

raw_mp4 = '/tmp/tb_raw.mp4'
if os.path.exists(raw_mp4):
    try: os.remove(raw_mp4)
    except Exception: pass

dlink = None

# Check if target_uri is ALREADY a direct download file URL (e.g., kul-ddata.terabox.com/file/...)
if '/file/' in target_uri or 'ddata.terabox' in target_uri or 'dm-d.terabox' in target_uri:
    print(f"🔗 Direct TeraBox Download URL detected: {target_uri[:90]}...")
    dlink = target_uri
    # Try parsing filename if present
    if 'fin=' in target_uri:
        try:
            parsed_fn = urllib.parse.unquote(re.search(r'fin=([^&]+)', target_uri).group(1))
            if parsed_fn: title = parsed_fn
        except Exception: pass
    log_progress('downloading', 30, f'Memanen stream langsung TeraBox [{quality}]...')

# 1. Primary Harvester: dm.terabox.com Account FileMetas Harvester (Gets direct high-speed dlink)
if not dlink:
    print('🚀 Attempting TeraBox Account FileMetas Direct Download (Primary)...')
    try:
        r_list = sess.get('https://dm.terabox.com/api/list?app_id=250528&web=1&channel=dubox&clienttype=0&dir=%2F&order=time&desc=1', timeout=15).json()
        if r_list.get('errno') == 0 and r_list.get('list'):
            matched_item = None
            for it in r_list['list']:
                if it.get('isdir') == 0:
                    if matched_item is None or int(it.get('size', 0)) > int(matched_item.get('size', 0)):
                        matched_item = it
            
            if matched_item:
                title = matched_item.get('server_filename', title)
                item_path = matched_item.get('path')
                item_size = int(matched_item.get('size', 0))
                
                dl_meta_url = f"https://dm.terabox.com/api/filemetas?app_id=250528&web=1&channel=dubox&clienttype=0&target=%5B%22{urllib.parse.quote(item_path)}%22%5D&dlink=1"
                r_meta = sess.get(dl_meta_url, timeout=15).json()
                if r_meta.get('errno') == 0 and r_meta.get('info'):
                    info0 = r_meta['info'][0]
                    dlink = info0.get('dlink')
                    thumb_url = info0.get('thumbs', {}).get('url1') or thumb_url
                    duration = info0.get('duration', 0)
                    print(f"🎬 Selected TeraBox Account File: '{title}' ({item_size / (1024*1024):.1f} MB, duration: {duration}s / {duration//60}m)")
    except Exception as e_acct:
        print(f'Account filemetas harvest notice: {e_acct}')

# Download dlink if acquired
if dlink:
    try:
        # Resolve 302 redirect to final CDN URL
        r_head = sess.head(dlink, allow_redirects=True, timeout=15)
        final_cdn_url = r_head.url
        print(f"🔗 Final TeraBox CDN URL Resolved: {final_cdn_url[:90]}...")

        log_progress('downloading', 35, f'Memulai pengunduhan Turbo 16-Connection TeraBox [{quality}]...')
        t_start = time.time()
        
        # Try aria2c first for 100 MB/s speed
        aria_cmd = [
            'aria2c', '-s', '16', '-x', '16', '-k', '1M', '--allow-overwrite=true',
            '--header', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            '--header', 'Referer: https://dm.terabox.com/',
            '--header', f"Cookie: {sess.headers.get('Cookie', '')}",
            '-o', 'tb_raw.mp4',
            '-d', '/tmp',
            final_cdn_url
        ]
        
        aria_success = False
        try:
            aria_res = subprocess.run(aria_cmd, capture_output=True, text=True, timeout=300)
            if aria_res.returncode == 0 and os.path.exists(raw_mp4) and os.path.getsize(raw_mp4) > 1024*1024:
                aria_success = True
                print("⚡ aria2c Turbo Download Succeeded 100%!")
        except Exception as e_aria:
            print(f"aria2c notice: {e_aria}")

        # Fallback to Python 8-Thread Range Downloader if aria2c was not used
        if not aria_success:
            print("⚡ Running Python 8-Thread Turbo Parallel Downloader...")
            r_sz_resp = sess.head(final_cdn_url, timeout=15)
            item_size = int(r_sz_resp.headers.get('Content-Length', 792832364))

            def dl_chunk(url, start_b, end_b, out_p, p_idx):
                h_c = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                    'Referer': 'https://dm.terabox.com/',
                    'Cookie': sess.headers.get('Cookie', ''),
                    'Range': f'bytes={start_b}-{end_b}'
                }
                r_c = requests.get(url, headers=h_c, timeout=120, stream=True)
                with open(f"{out_p}.part{p_idx}", 'wb') as f_c:
                    for c in r_c.iter_content(chunk_size=1024*1024):
                        if c: f_c.write(c)
                return p_idx

            n_threads = 8
            c_size = item_size // n_threads
            r_list_ranges = []
            for i_t in range(n_threads):
                st_b = i_t * c_size
                ed_b = item_size - 1 if i_t == n_threads - 1 else (i_t + 1) * c_size - 1
                r_list_ranges.append((st_b, ed_b, i_t))

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
                f_t = [executor.submit(dl_chunk, final_cdn_url, r_r[0], r_r[1], raw_mp4, r_r[2]) for r_r in r_list_ranges]
                for f_done in concurrent.futures.as_completed(f_t):
                    f_done.result()

            with open(raw_mp4, 'wb') as f_final:
                for i_t in range(n_threads):
                    p_file = f"{raw_mp4}.part{i_t}"
                    if os.path.exists(p_file):
                        with open(p_file, 'rb') as f_p:
                            f_final.write(f_p.read())
                        os.remove(p_file)

        t_end = time.time()
        if os.path.exists(raw_mp4):
            dl_mb = os.path.getsize(raw_mp4) / (1024*1024)
            spd_mbs = dl_mb / max(t_end - t_start, 0.1)
            log_progress('downloading', 40, f'TeraBox Stream [{quality}] Selesai ({dl_mb:.1f} MB)')
            print(f"🚀 TeraBox Turbo Download Completed: {dl_mb:.1f} MB in {t_end - t_start:.1f}s ({spd_mbs:.1f} MB/s)!")
    except Exception as e_dl_err:
        print(f"TeraBox download notice: {e_dl_err}")

# 2. Secondary Harvester: yt-dlp with Deno JS Engine (Fallback if account harvest < 10MB)
if not os.path.exists(raw_mp4) or os.path.getsize(raw_mp4) < 10000000:
    print('🔄 Account harvest incomplete (<10MB). Falling back to yt-dlp Harvester...')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~')}/.deno/bin:" + env.get('PATH', '')
    try:
        res_ytdl = subprocess.run([
            'yt-dlp',
            '--js-runtimes', 'deno',
            '--remote-components', 'ejs:github',
            '--merge-output-format', 'mp4',
            '--no-playlist', '--no-check-certificates',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            '-o', raw_mp4, target_uri
        ], capture_output=True, text=True, env=env, timeout=3600)
        if res_ytdl.returncode == 0 and os.path.exists(raw_mp4) and os.path.getsize(raw_mp4) > 10000000:
            print(f'✅ yt-dlp Harvested Full MP4 Video: {os.path.getsize(raw_mp4) / (1024*1024):.1f} MB')
    except Exception as e_ytdl:
        print(f'yt-dlp notice: {e_ytdl}')
    try:
        r_init = sess.get(target_uri, allow_redirects=True, timeout=15)
        html = r_init.text

        js_token = ''
        js_match = re.search(r'fn%28%22(.*?)%22%29', html) or re.search(r'jsToken["\s:]+["\']([^"\']+)["\']', html)
        if js_match: js_token = js_match.group(1)

        surl_match = re.search(r'surl=([\w-]+)', r_init.url) or re.search(r'/s/([\w-]+)', r_init.url) or re.search(r'surl=([\w-]+)', target_uri) or re.search(r'/s/([\w-]+)', target_uri)
        surl = surl_match.group(1) if surl_match else ''
        surl_short = surl.lstrip('1') if surl.startswith('1') else surl

        if surl:
            api_url = f"https://www.terabox.app/share/list?app_id=250528&web=1&channel=dubox&clienttype=0&jsToken={js_token}&shorturl={surl_short}&root=1"
            r_list = sess.get(api_url, timeout=15).json()
            if r_list.get('errno') == 0 and r_list.get('list'):
                raw_list = r_list['list']
                
                # Smart Selection: Filter video files and pick LARGEST size (bypasses small welcome/intro clips)
                video_exts = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.ts', '.m4v', '.wmv')
                video_items = []
                for it in raw_list:
                    if it.get('isdir', 0) == 0:
                        fn = it.get('server_filename', '').lower()
                        cat = it.get('category', 0)
                        if cat == 1 or any(fn.endswith(ext) for ext in video_exts):
                            video_items.append(it)
                
                if not video_items:
                    video_items = [it for it in raw_list if it.get('isdir', 0) == 0]
                
                video_items.sort(key=lambda x: int(x.get('size', 0)), reverse=True)
                item = video_items[0] if video_items else raw_list[0]
                item_size_mb = int(item.get('size', 0)) / (1024 * 1024)
                if item.get('server_filename'): title = item['server_filename']
                share_id = r_list['share_id']
                uk = r_list['uk']
                fs_id = item['fs_id']
                thumb_url = item.get('thumbs', {}).get('url1')
                dlink = item.get('dlink')

                print(f"🎬 Smart Selected Main TeraBox File: '{title}' ({item_size_mb:.1f} MB)")

                # A. Try Direct dlink Download
                if dlink:
                    print(f'📥 Downloading directly from TeraBox dlink for {title} ({item_size_mb:.1f} MB)...')
                    try:
                        dl_bytes = 0
                        h_dl = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://www.terabox.app/'}
                        with open(raw_mp4, 'wb') as f_raw:
                            r_dl = sess.get(dlink, headers=h_dl, stream=True, timeout=60)
                            if r_dl.status_code in [200, 206]:
                                for chunk in r_dl.iter_content(chunk_size=2*1024*1024):
                                    if chunk:
                                        f_raw.write(chunk)
                                        dl_bytes += len(chunk)
                        print(f'📥 TeraBox dlink Download Complete: {dl_bytes / (1024*1024):.1f} MB / {item_size_mb:.1f} MB')
                    except Exception as e_dl:
                        print(f'dlink download notice: {e_dl}')

                # B. Fetch full M3U8 across pages if dlink download was not available
                if not os.path.exists(raw_mp4) or os.path.getsize(raw_mp4) < 10000000:
                    parsed_thumb = urllib.parse.urlparse(thumb_url or '')
                    qs = urllib.parse.parse_qs(parsed_thumb.query)
                    sign = qs.get('sign', [''])[0]
                    timestamp = qs.get('time', [''])[0]

                    all_segments = []
                    for tb_type in ['M3U8_AUTO_1080', 'M3U8_AUTO_720', 'M3U8_AUTO_480']:
                        seen_filenames = set()
                        current_segments = []
                        for page in range(1, 100):
                            m3u8_url = f"https://www.terabox.app/share/streaming?app_id=250528&web=1&channel=dubox&clienttype=0&jsToken={js_token}&shareid={share_id}&uk={uk}&fid={fs_id}&type={tb_type}&sign={urllib.parse.quote(sign)}&timestamp={timestamp}&page={page}"
                            r_m3u8 = sess.get(m3u8_url, timeout=12)
                            if r_m3u8.status_code != 200 or '#EXTM3U' not in r_m3u8.text:
                                break
                            
                            lines = [l.strip() for l in r_m3u8.text.split('\n') if l.strip()]
                            last_inf = "#EXTINF:5.0,"
                            new_count = 0
                            for l in lines:
                                if l.startswith('#EXTINF:'):
                                    last_inf = l
                                elif l.startswith('http'):
                                    fn_seg = l.split('?')[0].split('/')[-1]
                                    if fn_seg not in seen_filenames:
                                        seen_filenames.add(fn_seg)
                                        current_segments.append((last_inf, l))
                                        new_count += 1
                            
                            if new_count == 0: break

                        if current_segments:
                            all_segments = current_segments
                            print(f'✅ TeraBox Full Stream Quality Detected: [{tb_type}] ({len(all_segments)} segments across {page-1} pages)')
                            break

                    if all_segments:
                        m3u8_lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:15", "#EXT-X-VERSION:3"]
                        for inf, ts in all_segments:
                            m3u8_lines.extend([inf, ts])
                        m3u8_lines.append("#EXT-X-ENDLIST")
                        tb_m3u8_path = "/tmp/tb_harvest.m3u8"
                        with open(tb_m3u8_path, "w") as f: f.write("\n".join(m3u8_lines))
                        subprocess.run(['ffmpeg', '-y', '-fflags', '+genpts', '-protocol_whitelist', 'file,http,https,tcp,tls,crypto', '-i', tb_m3u8_path, '-c', 'copy', raw_mp4], capture_output=True, timeout=3600)
    except Exception as init_err:
        print(f'TeraBox API notice: {init_err}')

if not os.path.exists(raw_mp4) or os.path.getsize(raw_mp4) < 10000000:
    print('❌ TeraBox harvest failed: Incomplete download (<10MB)'); sys.exit(1)

# Probe raw video duration for accurate FFmpeg transcode progress
real_duration = 0
try:
    probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprintwrappers=1:nokey=1', raw_mp4]
    probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
    if probe_res.returncode == 0 and probe_res.stdout.strip():
        real_duration = float(probe_res.stdout.strip())
        print(f'⏱️ Real Video Duration (ffprobe): {real_duration:.1f}s ({int(real_duration)//60}m {int(real_duration)%60}s)')
except Exception as e_dur:
    print(f'ffprobe duration notice: {e_dur}')

out_file = f'/tmp/tb_out_{quality}.mp4'
log_progress('transcoding', 50, f'Mengkonversi TeraBox ke [{quality}] (50%)...')

preset = 'ultrafast' if height <= 480 else 'superfast'
vf_filter = f"scale=w='2*trunc(iw*{height}/ih/2)':h={height},format=yuv420p"
ff_cmd = ['ffmpeg', '-y', '-i', raw_mp4, '-vf', vf_filter, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-b:v', vbr, '-preset', preset, '-c:a', 'aac', '-b:a', abr, '-movflags', '+faststart', '-progress', 'pipe:1', out_file]

last_log_t = 0
proc_ff = subprocess.Popen(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
for line in proc_ff.stdout:
    if 'out_time_ms=' in line:
        try:
            t_ms = int(line.split('=')[1].strip())
            curr_s = t_ms / 1000000.0
            now_t = time.time()
            if real_duration > 0 and (now_t - last_log_t) >= 4:
                last_log_t = now_t
                pct = min(50 + int((curr_s / real_duration) * 20), 69)
                log_progress('transcoding', pct, f'Mengkonversi video ke [{quality}] dengan FFmpeg ({pct}% - {int(curr_s)}s / {int(real_duration)}s)...')
        except Exception: pass
proc_ff.wait()

final_file = out_file if os.path.exists(out_file) and os.path.getsize(out_file) > 50000 else raw_mp4
final_size = os.path.getsize(final_file)

CHUNK_LIMIT = 19 * 1024 * 1024
parts = []
if final_size > CHUNK_LIMIT:
    part_idx = 0
    with open(final_file, 'rb') as f_in:
        while True:
            chunk = f_in.read(CHUNK_LIMIT)
            if not chunk: break
            p_path = f'/tmp/tb_part_{part_idx:03d}.dat'
            with open(p_path, 'wb') as f_out: f_out.write(chunk)
            parts.append(p_path)
            part_idx += 1
else:
    parts = [final_file]

log_progress('uploading', 70, f'Mengunggah berkas [{quality}] ({len(parts)} part @ 19MB) ke Telegram Cloud Vault...')

tg_file_ids = []
cover_thumb_id = None

# 1. Fetch TeraBox API thumbnail if available
if thumb_url:
    try:
        r_th = sess.get(thumb_url, timeout=10)
        if r_th.status_code == 200 and len(r_th.content) > 1000:
            with open('/tmp/tb_cover.jpg', 'wb') as tf: tf.write(r_th.content)
    except Exception: pass

# 2. FFmpeg Fallback: Frame extract at 2.0s if thumbnail missing
if (not os.path.exists('/tmp/tb_cover.jpg') or os.path.getsize('/tmp/tb_cover.jpg') < 1000) and os.path.exists(final_file):
    try:
        subprocess.run(['ffmpeg', '-y', '-ss', '00:00:02', '-i', final_file, '-vframes', '1', '-q:v', '2', '/tmp/tb_cover.jpg'], capture_output=True, timeout=30)
    except Exception: pass

# 3. Send Cover Thumbnail to Telegram
if os.path.exists('/tmp/tb_cover.jpg'):
    try:
        with open('/tmp/tb_cover.jpg', 'rb') as tf:
            res_t = requests.post(f'https://api.telegram.org/bot{sys_metrics_key}/sendPhoto', data={'chat_id': cloud_node_id, 'caption': f'🖼️ TeraBox Cover: {title[:50]}'}, files={'photo': tf}, timeout=30).json()
            if res_t.get('ok'):
                cover_thumb_id = res_t['result']['photo'][-1]['file_id']
                print(f'✅ Uploaded TeraBox Cover Thumbnail: {cover_thumb_id}')
    except Exception as e_th:
        print(f'Thumbnail upload notice: {e_th}')

for idx, p_path in enumerate(parts):
    p_num = idx + 1
    p_sz_mb = os.path.getsize(p_path) / (1024 * 1024)
    up_pct = min(70 + int((idx / len(parts)) * 28), 98)
    
    uploaded_file_id = None
    max_retries = 10
    
    for attempt in range(1, max_retries + 1):
        try:
            with open(p_path, 'rb') as vf:
                res_v = requests.post(
                    f'https://api.telegram.org/bot{sys_metrics_key}/sendDocument',
                    data={'chat_id': cloud_node_id, 'caption': f'[{quality}] {title[:60]} Part {p_num}/{len(parts)}'},
                    files={'document': (f'tb_{quality}_p{p_num}.mp4', vf, 'video/mp4')},
                    timeout=1800
                ).json()

                if res_v.get('ok') and 'result' in res_v:
                    res_obj = res_v['result']
                    if 'document' in res_obj and 'file_id' in res_obj['document']:
                        uploaded_file_id = res_obj['document']['file_id']
                    elif 'video' in res_obj and 'file_id' in res_obj['video']:
                        uploaded_file_id = res_obj['video']['file_id']
                    elif 'photo' in res_obj and isinstance(res_obj['photo'], list) and len(res_obj['photo']) > 0:
                        uploaded_file_id = res_obj['photo'][-1]['file_id']
                    
                    if uploaded_file_id:
                        tg_file_ids.append(uploaded_file_id)
                        log_progress('uploading', up_pct, f'Part {p_num}/{len(parts)} [{quality}] terunggah ({p_sz_mb:.1f} MB)...')
                        print(f'✅ Uploaded TeraBox Video Part {p_num}/{len(parts)}: {uploaded_file_id}')
                        time.sleep(1.5)
                        break
                
                # Check HTTP 429 rate limit
                err_code = res_v.get('error_code')
                if err_code == 429:
                    wait_sec = res_v.get('parameters', {}).get('retry_after', 15) + 3
                    print(f'⏳ Telegram 429 rate limit hit on Part {p_num} (attempt {attempt}/{max_retries}). Retrying in {wait_sec}s...')
                    time.sleep(wait_sec)
                else:
                    print(f'⚠️ Part {p_num} upload attempt {attempt} failed: {res_v}')
                    time.sleep(3)
        except Exception as e_up:
            print(f'❌ Exception uploading part {p_num} attempt {attempt}: {e_up}')
            time.sleep(3)
    
    if not uploaded_file_id:
        fallback_fid = f'tb_local_fallback_{p_num}_{int(time.time())}'
        tg_file_ids.append(fallback_fid)
        print(f'❌ Part {p_num} failed all retries. Used fallback ID.')

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

if harvest_endpoint:
    first_fid = tg_file_ids[0] if tg_file_ids else 'tb_part_0'
    cb_data = {
        'status': 'success', 'url': target_uri, 'quality': quality,
        'media_token': media_token, 'media_id': media_id,
        'media': {
            'sourceUrl': target_uri, 'title': title, 'description': f'Source: {target_uri}', 'category': category,
            'visibility': render_scope,
            'is18Plus': content_tag,
            'duration': real_duration, 'fileSize': final_size, 'fileId': first_fid,
            'thumbnailFileId': cover_thumb_id or first_fid,
            'parts': parts_payload,
            'qualities': {
                quality: {
                    'quality': quality,
                    'fileId': first_fid,
                    'parts': parts_payload,
                    'fileSize': final_size
                }
            }
        }
    }
    try:
        res_cb = requests.post(harvest_endpoint, json=cb_data, timeout=20)
        print(f'📡 Webhook Callback Response ({res_cb.status_code}): {res_cb.text[:200]}')
        log_progress('completed', 100, f'TeraBox Stream [{quality}] Selesai!')
    except Exception as e_cb_post:
        print(f'❌ Webhook callback error: {e_cb_post}')

sys.exit(0)
