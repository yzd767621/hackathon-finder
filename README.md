# Hackathon Finder

A free Windows app that finds hackathons that are **free to join, open to university students, and online, or in person in Kuala Lumpur**. Malaysian hackathons are listed first. It sends a Windows notification when new ones appear and shows everything on a simple web page.

For every hackathon it shows:

- **Difficulty**: Beginner / Intermediate / Advanced (estimated; the reason is shown)
- **Prizes**: each prize tagged **Cash** (converted to RM), **AI subscription** (Claude, ChatGPT, Gemini…), **Credits** or **Other**
- **Team size** (minimum and maximum), **format** (online / venue), **deadline**
- **Requirements**: who can join and what to submit

## Sources

| Source | What it adds |
|---|---|
| [Devpost](https://devpost.com) | Global online hackathons, plus Malaysia / KL / Selangor searches |
| [Devfolio](https://devfolio.co) | Online hackathons |
| [MLH](https://www.mlh.com) | Online student hackathons |
| [Luma](https://luma.com/kuala-lumpur) | Free hackathon-style events in KL |
| [UniNet](https://uninet.my) | Malaysian university student events |
| [GDG](https://gdg.community.dev) | Hackathons from Google Developer Group chapters in Malaysia |
| [Hackathon Radar](https://www.hackathonradar.com) | Upcoming Malaysian entries |
| DuckDuckGo / Bing | Malaysian university hackathon websites |

Everything uses public pages or feeds. No API keys or paid services are needed.

## Filters

- **Free**: events that mention a registration / entry fee are dropped (on any site that lists them)
- **Students**: high-school-only, postgrad/professional-only and women-only events, and events that exclude Malaysia, are dropped
- **Location**: online events are kept. If one has an in-person final, it's kept only when the final is in KL/Malaysia. In-person events must be in the KL / Klang Valley area.
- If a site doesn't respond, its hackathons from the last check stay on the list (labelled "from last check") instead of disappearing.

## Setup (Windows)

Requires Python 3.10+ and `curl` (built into Windows 10/11).

```powershell
python hackathon_notifier.py --open                                  # check now and open the page
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1          # check daily at 9:00 and at log-in
powershell -ExecutionPolicy Bypass -File make_desktop_icon.ps1       # desktop icon: refresh + open
```

To stop the daily check: `Unregister-ScheduledTask -TaskName "Hackathon Notifier" -Confirm:$false`

## Files

- `hackathon_notifier.py`: the app
- `report.html`: the generated page (not committed)
- `seen.json`: what has already been shown, cached pages, exchange rates (not committed)

Details are read automatically from each event's page. Always check the official rules before registering.
