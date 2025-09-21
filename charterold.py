import pygame
import json
import sys
import os

# --- Config ---
WIDTH, HEIGHT = 400, 300
FPS = 60
CIRCLE_RADIUS = 50
LONG_NOTE_THRESHOLD = 250  # ms

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 100, 100)
BLUE = (100, 100, 255)
GREEN = (100, 255, 100)
GRAY = (150, 150, 150)

# --- Initialize ---
pygame.init()
pygame.mixer.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Rhythm Game Charter")
clock = pygame.time.Clock()

# --- Game Variables ---
key_pressed = {pygame.K_LEFT: False, pygame.K_RIGHT: False}
press_start_time = {pygame.K_LEFT: None, pygame.K_RIGHT: None}
notes = []  # collected notes
song_start_time = None

# Circles positions
left_circle = (WIDTH // 4, HEIGHT // 2)
right_circle = (3 * WIDTH // 4, HEIGHT // 2)

# --- Load song ---
SONG_FILE = "bike.mp3"  # Change to your song file
pygame.mixer.music.load(SONG_FILE)
pygame.mixer.music.play()
song_start_time = pygame.time.get_ticks()

# --- Main Loop ---
running = True
while running:
    dt = clock.tick(FPS)
    screen.fill(BLACK)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Current song time
    song_time = pygame.time.get_ticks() - song_start_time

    # Input handling
    keys = pygame.key.get_pressed()

    for side, key in enumerate([pygame.K_LEFT, pygame.K_RIGHT]):
        # Key pressed
        if keys[key]:
            if not key_pressed[key]:
                key_pressed[key] = True
                press_start_time[key] = song_time
        # Key released
        else:
            if key_pressed[key]:
                key_pressed[key] = False
                start_time = press_start_time[key]
                duration = song_time - start_time if start_time is not None else 0

                if duration >= LONG_NOTE_THRESHOLD:
                    notes.append({"time": start_time, "side": side, "duration": duration})
                    print(f"Recorded LONG note: start={start_time}, side={side}, duration={duration}")
                else:
                    notes.append({"time": start_time, "side": side})
                    print(f"Recorded TAP note: time={start_time}, side={side}")

                press_start_time[key] = None

    # --- Draw circles ---
    # Left
    if key_pressed[pygame.K_LEFT]:
        pygame.draw.circle(screen, GRAY, left_circle, CIRCLE_RADIUS)
    pygame.draw.circle(screen, RED, left_circle, CIRCLE_RADIUS, 5)

    # Right
    if key_pressed[pygame.K_RIGHT]:
        pygame.draw.circle(screen, GRAY, right_circle, CIRCLE_RADIUS)
    pygame.draw.circle(screen, BLUE, right_circle, CIRCLE_RADIUS, 5)

    # Show current time
    font = pygame.font.SysFont(None, 36)
    text = font.render(f"Time: {song_time} ms", True, GREEN)
    screen.blit(text, (10, 10))

    pygame.display.flip()

# --- Save chart (sorted by time) ---
notes.sort(key=lambda n: n["time"])
chart_data = {"notes": notes}
with open("chart.json", "w") as f:
    json.dump(chart_data, f, indent=4)

print("Chart saved to chart.json")
pygame.quit()
sys.exit()