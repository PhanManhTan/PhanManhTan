#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GITHUB_GRAPHQL_API = "https://api.github.com/graphql"
LOCAL_TIMEZONE = timezone(timedelta(hours=7), "ICT")

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

THEMES = {
    "light": {
        "background": "#ffffff",
        "panel": "#f6f8fa",
        "text": "#1f2328",
        "muted": "#59636e",
        "border": "#d1d9e0",
        "levels": [
            "#ebedf0",
            "#9be9a8",
            "#40c463",
            "#30a14e",
            "#216e39",
        ],
    },
    "dark": {
        "background": "#0d1117",
        "panel": "#161b22",
        "text": "#f0f6fc",
        "muted": "#8b949e",
        "border": "#30363d",
        "levels": [
            "#161b22",
            "#0e4429",
            "#006d32",
            "#26a641",
            "#39d353",
        ],
    },
}

LEVEL_INDEX = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an animated GitHub contribution SVG."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--theme", choices=THEMES, default="dark")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--character-image",
        type=Path,
        default=Path("assets/docker-whale-transparent.png"),
        help="Image to embed as the animated character.",
    )
    return parser.parse_args()


def fetch_contributions(
    username: str,
    token: str,
    number_of_days: int,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    local_now = generated_at.astimezone(LOCAL_TIMEZONE)
    first_date = local_now.date() - timedelta(days=number_of_days - 1)
    start = datetime.combine(first_date, datetime.min.time(), tzinfo=LOCAL_TIMEZONE)
    start_utc = start.astimezone(timezone.utc)
    now_utc = local_now.astimezone(timezone.utc)

    request_body = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": username,
                "from": start_utc.isoformat().replace("+00:00", "Z"),
                "to": now_utc.isoformat().replace("+00:00", "Z"),
            },
        }
    ).encode("utf-8")

    request = Request(
        GITHUB_GRAPHQL_API,
        data=request_body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "phanmanhtan-contribution-animation",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed with HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub API request failed: {exc.reason}") from exc

    if payload.get("errors"):
        raise RuntimeError(payload["errors"])

    user = payload.get("data", {}).get("user")
    if user is None:
        raise RuntimeError(f"GitHub user not found: {username}")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    contributions_by_date = {
        contribution["date"]: contribution
        for week in calendar["weeks"]
        for contribution in week["contributionDays"]
    }

    contributions: list[dict[str, Any]] = []
    for index in range(number_of_days):
        current_date = first_date + timedelta(days=index)
        date_string = current_date.isoformat()
        contributions.append(
            contributions_by_date.get(
                date_string,
                {
                    "date": date_string,
                    "contributionCount": 0,
                    "contributionLevel": "NONE",
                },
            )
        )

    return contributions


def image_to_data_uri(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing character image: {path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type is None:
        mime_type = "application/octet-stream"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def key_times(*values: float) -> str:
    return ";".join(fmt(value) for value in values)


def generate_svg(
    username: str,
    contributions: list[dict[str, Any]],
    theme_name: str,
    character_image: Path,
) -> str:
    theme = THEMES[theme_name]
    character_data_uri = image_to_data_uri(character_image)

    width = 960
    height = 180
    panel_x = 20
    panel_y = 20
    panel_width = 920
    panel_height = 140
    start_x = 55
    block_y = 105
    available_width = 850
    block_count = len(contributions)
    block_step = available_width / max(block_count - 1, 1)
    block_size = min(20.0, max(4.0, block_step * 0.72))
    block_radius = min(5.0, block_size / 4)

    character_width = 132
    character_height = 98
    character_y = 35
    mouth_offset_x = 14
    character_start_x = start_x + available_width + 70
    character_end_x = start_x - character_width + 6
    travel_distance = character_start_x - character_end_x
    animation_duration = max(6, min(11, block_count * 0.32))

    blocks = []
    for index, contribution in enumerate(contributions):
        x_position = start_x + index * block_step
        block_center_x = x_position + (block_size / 2)
        level = str(contribution["contributionLevel"])
        level_index = LEVEL_INDEX.get(level, 0)
        color = theme["levels"][level_index]
        eat_at = (
            character_start_x
            + mouth_offset_x
            - block_center_x
        ) / travel_distance
        eat_at = clamp(eat_at, 0.08, 0.9)
        hold_until = clamp(eat_at - 0.025, 0.04, 0.88)
        bite_until = clamp(eat_at + 0.035, hold_until + 0.01, 0.94)
        vanish_at = clamp(eat_at + 0.07, bite_until + 0.01, 0.96)
        restore_at = 0.985
        block_key_times = key_times(
            0,
            hold_until,
            bite_until,
            vanish_at,
            restore_at,
            1,
        )
        count = int(contribution["contributionCount"])
        date = html.escape(str(contribution["date"]))
        suffix = "" if count == 1 else "s"
        title = f"{date}: {count} contribution{suffix}"
        bite_x = x_position + 22
        bite_y = block_y - 18

        blocks.append(
            f"""<g>
  <title>{title}</title>
  <rect
    x="{fmt(x_position)}"
    y="{block_y}"
    width="{fmt(block_size)}"
    height="{fmt(block_size)}"
    rx="{fmt(block_radius)}"
    fill="{color}"
    stroke="{theme['border']}"
  >
    <animate
      attributeName="opacity"
      values="1;1;.45;0;0;1"
      keyTimes="{block_key_times}"
      begin="0s"
      dur="{fmt(animation_duration)}s"
      repeatCount="indefinite"
    />
    <animate
      attributeName="x"
      values="{fmt(x_position)};{fmt(x_position)};{fmt(bite_x)};{fmt(bite_x)};{fmt(x_position)}"
      keyTimes="{key_times(0, hold_until, bite_until, restore_at, 1)}"
      begin="0s"
      dur="{fmt(animation_duration)}s"
      repeatCount="indefinite"
    />
    <animate
      attributeName="y"
      values="{block_y};{block_y};{fmt(bite_y)};{fmt(bite_y)};{block_y}"
      keyTimes="{key_times(0, hold_until, bite_until, restore_at, 1)}"
      begin="0s"
      dur="{fmt(animation_duration)}s"
      repeatCount="indefinite"
    />
    <animate
      attributeName="width"
      values="{fmt(block_size)};{fmt(block_size)};4;0;0;{fmt(block_size)}"
      keyTimes="{block_key_times}"
      begin="0s"
      dur="{fmt(animation_duration)}s"
      repeatCount="indefinite"
    />
    <animate
      attributeName="height"
      values="{fmt(block_size)};{fmt(block_size)};4;0;0;{fmt(block_size)}"
      keyTimes="{block_key_times}"
      begin="0s"
      dur="{fmt(animation_duration)}s"
      repeatCount="indefinite"
    />
  </rect>
</g>"""
        )

    safe_username = html.escape(username)

    return f"""<svg
  xmlns="http://www.w3.org/2000/svg"
  width="{width}"
  height="{height}"
  viewBox="0 0 {width} {height}"
  role="img"
  aria-labelledby="title description"
>
  <title id="title">{safe_username}'s last {block_count} days of contributions</title>
  <desc id="description">An animated Docker whale eats a GitHub contribution timeline.</desc>

  <rect width="100%" height="100%" rx="18" fill="{theme['background']}" />
  <rect
    x="{panel_x}"
    y="{panel_y}"
    width="{panel_width}"
    height="{panel_height}"
    rx="16"
    fill="{theme['panel']}"
    stroke="{theme['border']}"
  />

  <line
    x1="45"
    y1="115"
    x2="915"
    y2="115"
    stroke="{theme['border']}"
    stroke-width="2"
  />

  {"".join(blocks)}

  <g>
    <animateTransform
      attributeName="transform"
      type="translate"
      values="{fmt(character_start_x)} {character_y};{fmt(character_end_x)} {character_y}"
      dur="{fmt(animation_duration)}s"
      repeatCount="indefinite"
    />
    <g>
      <animateTransform
        attributeName="transform"
        type="translate"
        values="0 0;0 -5;0 0"
        keyTimes="0;.5;1"
        dur=".9s"
        repeatCount="indefinite"
      />
      <image
        href="{character_data_uri}"
        width="{character_width}"
        height="{character_height}"
        preserveAspectRatio="xMidYMid meet"
      />
    </g>
  </g>
</svg>
"""


def main() -> None:
    arguments = parse_arguments()

    if not 1 <= arguments.days <= 365:
        raise SystemExit("--days must be between 1 and 365")

    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise SystemExit("GITHUB_TOKEN environment variable is required")

    repository_root = Path(__file__).resolve().parents[1]
    character_image = arguments.character_image
    if not character_image.is_absolute():
        character_image = repository_root / character_image

    generated_at = datetime.now(LOCAL_TIMEZONE)
    contributions = fetch_contributions(
        username=arguments.username,
        token=github_token,
        number_of_days=arguments.days,
        generated_at=generated_at,
    )
    svg = generate_svg(
        username=arguments.username,
        contributions=contributions,
        theme_name=arguments.theme,
        character_image=character_image,
    )

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(svg, encoding="utf-8")

    print(f"Generated: {arguments.output}")


if __name__ == "__main__":
    main()
