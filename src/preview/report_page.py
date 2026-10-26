"""The saved report's response charts: the live preview's three cards (`preview.page`), laid out for a
scrolling page instead of a viewport.

    [ verdict strip: result, event, what trips and when it is back ]
    [ Voltage at the load bus ] [ Power output + state strip ]
    [ Voltage vs. standard: chart | result pill, sentence, legend ]

The figures are the live page's own (`preview.page.figures`), so the report and the app never drift. A report
holds several of these (one per block) and no running app, so each block gets its own element ids, draws
once, and relies on the single plotly.js the report embeds. Qt-free.
"""

from __future__ import annotations

import base64
import json
from html import escape

from app import tokens as t
from app.resources import resource_path
from preview.model import TRIPS, PreviewResult
from preview.page import _parts, figures

# Faces the report embeds so it reads the same on a machine without IBM Plex installed.
_FONTS = ((t.FONT_SANS, 400, "IBMPlexSans-Regular.ttf"), (t.FONT_SANS, 600, "IBMPlexSans-SemiBold.ttf"),
          (t.FONT_MONO, 400, "IBMPlexMono-Regular.ttf"))
_NOTE_COLORS = {"error": (t.TRIP_TEXT, "Error"), "warning": (t.WARNING_TEXT, "Warning"), "info": (t.TEXT_MUTED, "Note")}
PLOT_CONFIG = {"responsive": True, "displaylogo": False, "displayModeBar": False}


def font_face_css() -> str:
    faces = []
    for family, weight, name in _FONTS:
        path = resource_path("assets", "fonts", name)
        if path.is_file():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            faces.append(f"@font-face {{ font-family: '{family}'; font-weight: {weight}; "
                         f"src: url(data:font/ttf;base64,{data}) format('truetype'); }}")
    return "\n".join(faces)


REPORT_BLOCK_CSS = f"""
.rb {{ margin: 12px 0 8px; }}
.rb-verdict {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; padding: 10px 14px;
              border-radius: {t.RADIUS_CARD}px; border: 1px solid {t.CARD_BORDER}; background: {t.SURFACE}; }}
.rb-verdict.trips {{ background: {t.TRIP_BANNER}; border-color: {t.TRIP_BANNER_BORDER}; }}
.rb-verdict.rides {{ background: {t.RIDE_BANNER}; border-color: {t.RIDE_BANNER_BORDER}; }}
.rb-badge {{ border-radius: {t.RADIUS_TAG}px; padding: 4px 10px; font-size: 12px; font-weight: 600;
            letter-spacing: 1px; color: {t.WHITE}; }}
.rb-verdict.trips .rb-badge {{ background: {t.TRIP}; }}
.rb-verdict.rides .rb-badge {{ background: {t.BRAND}; }}
.rb-what {{ flex: 1 1 260px; min-width: 0; }}
.rb-what b {{ display: block; font-weight: 600; font-size: 14px; }}
.rb-what span {{ color: {t.TEXT_MUTED}; font-size: 12px; }}
.rb-stats {{ display: flex; gap: 22px; }}
.rb-stat span {{ display: block; color: {t.TEXT_MUTED}; font-size: 11px; }}
.rb-stat b {{ font-family: {t.CSS_FONT_MONO}; font-weight: 400; font-size: 14px; color: {t.POWER}; }}
.rb-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: {t.GUTTER}px; margin-top: {t.GUTTER}px; }}
.rb-grid .card {{ background: {t.SURFACE}; border: 1px solid {t.CARD_BORDER}; border-radius: {t.RADIUS_CARD}px;
                  padding: 12px 14px 8px; min-width: 0; box-sizing: border-box; }}
.rb-grid .card.wide {{ grid-column: 1 / span 2; }}
.rb-grid .head {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; margin-bottom: 4px; }}
.rb-grid .title {{ font-weight: 600; font-size: 13px; }}
.rb-grid .title .sub {{ font-weight: 400; color: {t.TEXT_MUTED}; }}
.rb-grid .legend {{ display: flex; flex-wrap: wrap; gap: 4px 12px; color: {t.TEXT_MUTED}; font-size: 11px; margin-left: auto; }}
.rb-grid .sw {{ display: inline-block; width: 14px; margin-right: 5px; vertical-align: middle; border-radius: 2px; }}
.rb-plot {{ height: 270px; }}
.rb-wide {{ display: flex; gap: 18px; align-items: stretch; }}
.rb-wide .rb-plot {{ flex: 1.6 1 0; height: 300px; min-width: 0; }}
.rb-grid .info {{ flex: 1 1 0; display: flex; flex-direction: column; justify-content: center; gap: 10px; padding-right: 8px; }}
.rb-grid .pill {{ align-self: flex-start; border-radius: {t.RADIUS_TAG}px; padding: 3px 10px; font-weight: 600; font-size: 13px; }}
.rb-grid .pill.ok {{ background: {t.BRAND_TINT}; color: {t.BRAND_DARK}; }}
.rb-grid .pill.bad {{ background: {t.TRIP_TINT}; color: {t.TRIP_TEXT}; }}
.rb-grid .pill.neutral {{ background: {t.HAIRLINE}; color: {t.TEXT_MUTED}; }}
.rb-grid .sentence {{ margin: 0; line-height: 1.45; }}
.rb-grid .legend-col {{ display: flex; flex-direction: column; gap: 6px; color: {t.TEXT_MUTED}; font-size: 12px; }}
.rb-notes {{ margin: 10px 0 0 18px; padding: 0; font-size: 12px; }}
@media (max-width: 760px) {{
  .rb-grid {{ grid-template-columns: 1fr; }} .rb-grid .card.wide {{ grid-column: auto; }} .rb-wide {{ flex-direction: column; }}
}}
@media print {{ .rb-grid .card, .rb-verdict {{ break-inside: avoid; }} }}
"""


def _notes_html(notes) -> str:
    if not notes:
        return ""
    items = "".join(f'<li style="color:{_NOTE_COLORS[level][0]};"><b>{_NOTE_COLORS[level][1]}:</b> {escape(text)}</li>'
                    for level, text in notes)
    return f'<ul class="rb-notes">{items}</ul>'


def _verdict_html(result: PreviewResult) -> str:
    state = "trips" if result.verdict == TRIPS else "rides"
    stats = "".join(f'<div class="rb-stat"><span>{name}</span><b>{escape(value)}</b></div>'
                    for name, value in (("Load tripped", result.load_tripped), ("Reconnects", result.reconnects),
                                        ("Ramp", result.ramp)))
    return (f'<div class="rb-verdict {state}"><span class="rb-badge">{escape(result.verdict)}</span>'
            f'<div class="rb-what"><b>{escape(result.title)}</b><span>{escape(result.detail)}</span></div>'
            f'<div class="rb-stats">{stats}</div></div>')


def render_report_block(result: PreviewResult, preset, key: str, notes=()) -> str:
    """One block's verdict strip, three cards and notes. `key` makes the element ids unique within the report
    ("it" gives plot-it-v, plot-it-p, plot-it-s); the page must already have plotly.js loaded."""
    data = {f"plot-{key}-{plot_id[-1]}": json.loads(fig.to_json()) for plot_id, fig in figures(result, preset).items()}
    parts = _parts(result)
    ids = {plot_id: f"plot-{key}-{plot_id[-1]}" for plot_id in ("plot-v", "plot-p", "plot-s")}
    return f"""
<div class="rb">
  {_verdict_html(result)}
  <div class="rb-grid">
    <div class="card"><div class="head"><span class="title">{parts['title-v']}</span>
      <span class="legend">{parts['legend-v']}</span></div><div class="rb-plot" id="{ids['plot-v']}"></div></div>
    <div class="card"><div class="head"><span class="title">{parts['title-p']}</span>
      <span class="legend">{parts['legend-p']}</span></div><div class="rb-plot" id="{ids['plot-p']}"></div></div>
    <div class="card wide"><div class="head"><span class="title">{parts['title-s']}</span></div>
      <div class="rb-wide"><div class="rb-plot" id="{ids['plot-s']}"></div><div class="info">{parts['info-s']}</div></div></div>
  </div>
  {_notes_html(notes)}
  <script>
  (function () {{
    var figs = {json.dumps(data)}, config = {json.dumps(PLOT_CONFIG)};
    Object.keys(figs).forEach(function (id) {{ Plotly.newPlot(id, figs[id].data, figs[id].layout, config); }});
  }})();
  </script>
</div>"""
