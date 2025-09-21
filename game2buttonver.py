import pygame
import sys
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from tkinter import simpledialog
import shutil
import RPi.GPIO as GPIO


# --- Config ---
WIDTH, HEIGHT = 400, 600
FPS = 60
SQUARE_SIZE = 50
SPEED = 8  # pixels per frame
HIT_ZONE_Y = HEIGHT - 100
JUDGMENT_DISPLAY = 1000  # milliseconds
HIT_DISTANCE_THRESHOLD = 70
HOLD_POINT_RATE = 0.1  # points per ms while holding

GPIO.setmode(GPIO.BCM)
LEFT_PIN = 23
RIGHT_PIN = 4
GPIO.setup(LEFT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(RIGHT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 100, 100)
BLUE = (100, 100, 255)
GREEN = (100, 255, 100)
YELLOW = (255, 255, 0)
GRAY = (180, 180, 180)


# --- Initialize Pygame ---
pygame.init()
try:
    pygame.mixer.init()
except Exception as e:
    print("Warning: audio init failed:", e)
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("2-Button Rhythm Game")
clock = pygame.time.Clock()

# --- Game Variables ---
squares = []
score = 0
hold_points_acc = 0.0
judgment = ""
judgment_timer = 0
key_pressed = {pygame.K_LEFT: False, pygame.K_RIGHT: False}
button_pressed = {LEFT_PIN: False, RIGHT_PIN: False}
hold_frames = 0  # add this at top with other globals


# Hit zones
hit_zones = [
    (WIDTH//4 - SQUARE_SIZE//2, HIT_ZONE_Y - SQUARE_SIZE//2),
    (3*WIDTH//4 - SQUARE_SIZE//2, HIT_ZONE_Y - SQUARE_SIZE//2)
]

travel_distance = HIT_ZONE_Y - (-SQUARE_SIZE)
travel_time_ms = (travel_distance / SPEED) * (1000 / FPS)

# --- Menu / Level Loading ---
SONGS_DIR = Path("songs")
levels = []
selected_level = 0

def scan_levels():
    global levels, selected_level
    levels = []
    if not SONGS_DIR.exists():
        SONGS_DIR.mkdir()
    for folder in sorted(SONGS_DIR.iterdir()):
        if folder.is_dir():
            level_json = folder / "level.json"
            chart_json = folder / "chart.json"
            if level_json.exists() and chart_json.exists():
                try:
                    meta = json.loads(level_json.read_text(encoding="utf-8"))
                    chart = json.loads(chart_json.read_text(encoding="utf-8")).get("notes", [])
                    audio_path = None
                    if "audio" in meta:
                        candidate = folder / meta["audio"]
                        if candidate.exists():
                            audio_path = candidate
                    if audio_path is None:
                        for ext in (".mp3", ".ogg", ".wav"):
                            found = list(folder.glob(f"*{ext}"))
                            if found:
                                audio_path = found[0]
                                break
                    if audio_path is None:
                        continue
                    meta["audio_path"] = str(audio_path)
                    levels.append({"folder": folder, "meta": meta, "chart": chart})
                except Exception as e:
                    print("Error reading level:", folder, e)
    # Always add "New Level" as a pseudo entry
    levels.append({"folder": None, "meta": {"name": "[New Level]"}, "chart": []})
    if levels:
        selected_level = max(0, min(selected_level, len(levels)-1))
    else:
        selected_level = 0

scan_levels()

# --- State ---
state = "menu"  # menu, playing, results
note_index = 0
song_start_time = None
current_level = None
song_length_ms = 0
perfect_possible = 0
final_score = 0
final_perfect = 0
level_end_trigger = None  # <-- new

# --- Helper Functions ---
def draw_hit_zones():
    for x, y in hit_zones:
        pygame.draw.rect(screen, GREEN, (x, y, SQUARE_SIZE, SQUARE_SIZE), 3)

def calculate_score(distance):
    max_score = 100
    if distance < 20:
        return max_score, "Perfect"
    elif distance < 35:
        return int(max_score * 0.7), "Good"
    elif distance < 50:
        return int(max_score * 0.4), "Near"
    else:
        return 0, "Miss"

def reset_play_state():
    global squares, score, judgment, judgment_timer, key_pressed, note_index, song_start_time, perfect_possible, hold_points_acc, level_end_trigger
    squares = []
    score = 0
    hold_points_acc = 0.0
    judgment = ""
    judgment_timer = 0
    key_pressed = {pygame.K_LEFT: False, pygame.K_RIGHT: False}
    note_index = 0
    song_start_time = None
    perfect_possible = 0
    level_end_trigger = None


def handle_input(song_time, dt):
    global score, hold_frames, judgment, judgment_timer
    keys = pygame.key.get_pressed()
    for side, key in enumerate([pygame.K_LEFT, pygame.K_RIGHT]):
        if keys[key]:
            if not key_pressed[key]:
                key_pressed[key] = True
                # Try to hit head
                closest_sq = None
                min_distance = float('inf')
                for sq in squares:
                    if sq['side'] == side and not sq.get("hit_start", False):
                        distance = abs(sq['y'] + SQUARE_SIZE//2 - HIT_ZONE_Y)
                        if distance < min_distance and distance < HIT_DISTANCE_THRESHOLD:
                            min_distance = distance
                            closest_sq = sq
                if closest_sq:
                    pts, msg = calculate_score(min_distance)
                    score += pts
                    judgment = msg
                    judgment_timer = pygame.time.get_ticks()
                    if closest_sq.get("duration", 0) > 0:
                        closest_sq["hit_start"] = True
                        head_y_at_perfect_end = HIT_ZONE_Y + 20
                        frames_to_perfect_end = max((head_y_at_perfect_end - closest_sq['y']) / SPEED, 0)
                        closest_sq["start_time"] = song_time + frames_to_perfect_end * (1000 / FPS)
                    else:
                        squares.remove(closest_sq)
            # Holding long notes (inside handle_input, for the given side)
            for sq in squares:
                if sq['side'] == side and sq.get("duration", 0) > 0 and sq.get("hit_start", False):
                    if song_time >= sq.get("start_time", 0) and song_time <= sq["end_time"]:
                        sq["hold_frames"] += 1
                        if sq["hold_frames"] >= 2:
                            score += 5
                            sq["hold_frames"] = 0


        else:
            key_pressed[key] = False
            
    for side, pin in enumerate([LEFT_PIN, RIGHT_PIN]):
        pressed = not GPIO.input(pin)
        if pressed:
            if not button_pressed[pin]:
                button_pressed[pin] = True
                closest_sq = None
                min_distance = float('inf')

                for sq in squares:
                    if sq['side'] == side:
                        distance = abs(sq['y'] + SQUARE_SIZE//2 - HIT_ZONE_Y)
                        if distance < min_distance and distance < 100:
                            min_distance = distance
                            closest_sq = sq

                if closest_sq:
                    pts, msg = calculate_score(min_distance)
                    squares.remove(closest_sq)
                    score += pts
                    judgment = msg
                    judgment_timer = pygame.time.get_ticks()
        else:
            button_pressed[pin] = False

def start_level(level):
    global state, current_level, song_start_time, song_length_ms, note_index, perfect_possible
    reset_play_state()
    current_level = level
    note_index = 0
    song_start_time = None
    song_length_ms = level['meta'].get('length_ms', 0)
    
    perfect_possible = 0
    for n in level['chart']:
        if 'duration' in n and n['duration'] > 0:
            duration_sec = n['duration'] / 1000.0
            hold_frames = int(duration_sec * FPS)
            body = (hold_frames // 2) * 5
            perfect_possible += 100 + body
        else:
            perfect_possible += 100




    try:
        pygame.mixer.music.stop()
    except:
        pass
    try:
        pygame.mixer.music.load(level['meta']['audio_path'])
        pygame.mixer.music.play()
    except Exception as e:
        print("Audio play error:", e)
    song_start_time = pygame.time.get_ticks()
    state = "playing"


def end_level_and_show_results():
    global state, final_score, final_perfect
    try: pygame.mixer.music.stop()
    except: pass
    final_score = int(score)
    final_perfect = int(perfect_possible)
    state = "results"

def create_new_level():
    root = tk.Tk()
    root.withdraw()

    # Pick song file
    song_path = filedialog.askopenfilename(title="Select Song", filetypes=[("Audio Files", "*.mp3 *.ogg *.wav")])
    if not song_path:
        return

    # Ask name & difficulty
    # Ask name & difficulty using GUI dialogs
    name = simpledialog.askstring("Level Info", "Enter level name:")
    if not name:
        return
    difficulty = simpledialog.askstring("Level Info", "Enter difficulty:")
    if not difficulty:
        difficulty = "Unknown"


    # Pick folder name
    num = 1
    while (SONGS_DIR / f"level{num}").exists():
        num += 1
    folder = SONGS_DIR / f"level{num}"
    folder.mkdir()

    # Copy song
    song_file = os.path.basename(song_path)
    dest_song = folder / song_file
    shutil.copy(song_path, dest_song)

    # Get length in ms
    try:
        snd = pygame.mixer.Sound(str(dest_song))
        length_ms = int(snd.get_length() * 1000)
    except:
        length_ms = 0

    # Write metadata
    meta = {
        "name": name,
        "difficulty": difficulty,
        "audio": song_file,
        "length_ms": length_ms
    }
    (folder / "level.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Empty chart for now
    (folder / "chart.json").write_text(json.dumps({"notes":[]}, indent=2), encoding="utf-8")

    print(f"Created new level at {folder}")


# --- Main Loop ---
running = True
while running:
    dt = clock.tick(FPS)
    screen.fill(BLACK)
    now = pygame.time.get_ticks()
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if state == "menu" and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RIGHT:
                if levels: selected_level = (selected_level + 1) % len(levels)
            elif event.key == pygame.K_LEFT:
                if levels: selected_level = (selected_level - 1) % len(levels)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if levels:
                    if levels[selected_level]['meta']['name'] == "[New Level]":
                        create_new_level()
                        scan_levels()
                    else:
                        start_level(levels[selected_level])
            elif event.key == pygame.K_r: scan_levels()
        elif state == "results" and event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                scan_levels()
                state = "menu"

    # --- MENU ---
    if state == "menu":
        title_font = pygame.font.SysFont(None, 48)
        screen.blit(title_font.render("Rhythm Game", True, WHITE), (WIDTH//2 - 120, 40))
        small = pygame.font.SysFont(None, 28)
        if not levels:
            info = small.render("No levels found in 'songs/' folder.", True, YELLOW)
            screen.blit(info, (20, 120))
        else:
            lev = levels[selected_level]
            meta = lev['meta']
            if meta.get("name") == "[New Level]":
                # Show only "Add Level"
                big = pygame.font.SysFont(None, 48)
                text = big.render("Add Level", True, YELLOW)
                screen.blit(text, (WIDTH//2 - text.get_width()//2, HEIGHT//2 - text.get_height()//2))
            else:
                screen.blit(small.render(f"Name: {meta.get('name','?')}", True, WHITE), (20,140))
                screen.blit(small.render(f"Difficulty: {meta.get('difficulty','?')}", True, WHITE), (20,170))
                screen.blit(small.render(f"Length: {meta.get('length_ms',0)//1000}s", True, WHITE), (20,200))
                if lev['folder']:
                    screen.blit(small.render(f"Folder: {lev['folder'].name}", True, GRAY), (20,230))
                tip = small.render("Use ← / → to switch levels. Enter to play. Press R to refresh.", True, YELLOW)
                screen.blit(tip, (20, HEIGHT - 40))
                # chart preview
                preview_top = 260
                preview_left = 40
                preview_w = WIDTH - 80
                preview_h = 200
                pygame.draw.rect(screen, (40,40,40), (preview_left, preview_top, preview_w, preview_h))
                chart = lev['chart']
                length_ms = meta.get('length_ms', 60000)
                if length_ms > 0:
                    for n in chart[:200]:
                        t = n['time']/max(1,length_ms)
                        x = preview_left + int(t*preview_w)
                        y = preview_top + (preview_h//4 if n['side']==0 else 3*preview_h//4)
                        color = RED if n['side']==0 else BLUE
                        if 'duration' in n and n['duration']>0:
                            pygame.draw.line(screen, color, (x,y-5), (x,y+5), 4)
                        else:
                            pygame.draw.circle(screen, color, (x,y), 3)



    # --- PLAYING ---
    elif state == "playing":
        song_time = pygame.time.get_ticks() - song_start_time
        # when spawning a note (replace your current spawning code inside the while loop)
        while note_index < len(current_level['chart']) and current_level['chart'][note_index]["time"] - travel_time_ms <= song_time:
            note = current_level['chart'][note_index]
            side = note["side"]
            color = RED if side == 0 else BLUE
            x = hit_zones[side][0]
            # compute spawn_time (song_time when this square should appear at top)
            spawn_time = note["time"] - travel_time_ms
            sq = {
                'x': x,
                'y': -SQUARE_SIZE,          # initial fallback, actual y computed from song_time
                'color': color,
                'side': side,
                'note_time': note["time"],  # absolute ms in song when head should be at hit zone
                'spawn_time': spawn_time,   # absolute ms in song when it was spawned
                'hold_frames': 0
            }
            if "duration" in note:
                sq["duration"] = note["duration"]            # ms
                sq["end_time"] = note["time"] + note["duration"]
                sq["hit_start"] = False
            squares.append(sq)
            note_index += 1

        # Time-driven movement + drawing + removal
        for sq in squares[:]:
            # compute normalized progress from spawn -> hit zone
            # clamp progress 0..1 for head movement
            if travel_time_ms > 0:
                progress = (song_time - sq['spawn_time']) / travel_time_ms
            else:
                progress = 1.0
            # y = start_y + progress * travel_distance
            sq_y = -SQUARE_SIZE + progress * travel_distance
            sq['y'] = sq_y

            # If this is a long note, draw tail that shows remaining hold length
            if sq.get("duration", 0) > 0:
                # tail_pixels corresponds to how many pixels the hold should occupy at given travel_time scale
                tail_pixels = int((sq["duration"] / travel_time_ms) * travel_distance) if travel_time_ms>0 else 0
                # tail top is sq_y - tail_pixels (the tail extends upward from head)
                pygame.draw.rect(screen, GRAY, (sq['x'] + SQUARE_SIZE//4, sq_y - tail_pixels, SQUARE_SIZE//2, tail_pixels))
            # draw head
            pygame.draw.rect(screen, sq['color'], (sq['x'], sq_y, SQUARE_SIZE, SQUARE_SIZE))

            # REMOVAL conditions based on song_time (timeline) and position:
            #  - for non-long notes: if song_time > note_time + some grace -> remove (miss)
            #  - for long notes not hit: if song_time > note_time + travel_time_ms + small_grace -> remove as missed (never hit)
            #  - for long notes after hit_start: remove when song_time > end_time + travel_time_ms (tail passed)
            # Use small grace to allow off-by-one/frame.
            GRACE_MS = 30
            if sq.get("duration",0) > 0:
                # long note
                if not sq.get("hit_start", False):
                    # If song_time has passed the note's head time + travel_time (meaning head already should have reached and passed),
                    # and the rendered head is below the hit zone by more than SQUARE_SIZE, treat as missed
                    if song_time > sq['note_time'] + GRACE_MS and sq_y > HIT_ZONE_Y + SQUARE_SIZE:
                        judgment = "Miss"
                        judgment_timer = pygame.time.get_ticks()
                        squares.remove(sq)
                else:
                    # already started holding; remove after the note's end_time + travel_time (tail fully passed)
                    if song_time > sq['end_time'] + travel_time_ms + GRACE_MS:
                        squares.remove(sq)
            else:
                # short note: if we've already passed the note_time + a bit and the head is below screen, mark miss and remove
                if song_time > sq['note_time'] + GRACE_MS and sq_y > HEIGHT:
                    pts, msg = calculate_score(abs(sq_y + SQUARE_SIZE - HIT_ZONE_Y))
                    if pts == 0:
                        judgment = "Miss"
                        judgment_timer = pygame.time.get_ticks()
                    squares.remove(sq)

        handle_input(song_time, dt)
        draw_hit_zones()

        # --- End detection ---
        if note_index >= len(current_level['chart']) and not squares:
            if level_end_trigger is None:
                level_end_trigger = pygame.time.get_ticks()  # start countdown
            elif pygame.time.get_ticks() - level_end_trigger > 3000:  # 3s delay
                end_level_and_show_results()
        
        font = pygame.font.SysFont(None, 36)
        screen.blit(font.render(f"Score: {int(score)}", True, WHITE), (10,10))
        if pygame.time.get_ticks()-judgment_timer<JUDGMENT_DISPLAY:
            jfont=pygame.font.SysFont(None,40)
            screen.blit(jfont.render(judgment, True, YELLOW), (WIDTH//2 - 60, HEIGHT-50))

    # --- RESULTS ---
    elif state == "results":
        title_font = pygame.font.SysFont(None,44)
        small = pygame.font.SysFont(None,28)
        screen.blit(title_font.render("Results", True, WHITE), (WIDTH//2-60,40))
        screen.blit(small.render(f"Score: {final_score}", True, YELLOW), (40,120))
        screen.blit(small.render(f"Perfect possible: {final_perfect}", True, WHITE), (40,160))
        pct = (final_score/final_perfect*100.0) if final_perfect>0 else 0.0
        screen.blit(small.render(f"Accuracy: {pct:.2f}%", True, GREEN), (40,200))
        screen.blit(small.render("Press Enter or Esc to return to menu", True, GRAY), (40, HEIGHT-80))

    # --- FPS ---
    fps_font = pygame.font.SysFont(None,18)
    screen.blit(fps_font.render(f"FPS: {int(clock.get_fps())}", True, GRAY), (WIDTH-70,10))

    pygame.display.flip()

pygame.quit()
sys.exit()
