# Hackathon Finder

A free Windows app that finds hackathons that are **open to university students, and online, or in person in Kuala Lumpur**, and recommends the ones where you have the best chance of winning cash. Malaysian hackathons are listed first. It sends a Windows notification when new ones appear and shows everything on a simple web page.

For every hackathon it shows:

- **Difficulty**: Beginner / Intermediate / Advanced (estimated; the reason is shown)
- **Prizes**: each prize tagged **Cash** (converted to RM), **AI subscription** (Claude, ChatGPT, Gemini…), **Credits** or **Other**
- **Cost**: **Free** or **Fee: RM X** (paid hackathons are listed and labelled, not hidden)
- **Participants**: registrations from Devpost / Devfolio / Luma, or the number stated on the event page
- **Win odds**: estimated chance of winning a cash prize, and expected cash per team after any fee
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

## Easiest cash to win

The top of the page ranks hackathons by how likely you are to win a cash prize:

- **Competition**: competing teams = participants ÷ team size (on Devpost / Devfolio only ~12% of registrants submit). Early registration counts are topped up to a typical minimum; when no count is published a typical size is guessed (25 teams for in-person KL events, 50 for Malaysian online, 200 for global online) and marked "guess".
- **Prizes**: number of cash prizes ÷ competing teams.
- **Difficulty**: odds are scaled down for Intermediate (×0.65) and Advanced (×0.4) events.
- **Fee**: subtracted from expected winnings; hackathons whose fee is more than the expected winnings are not recommended.

Only hackathons with a top cash prize of at least RM 500 are recommended. Use the sort menu for "Easiest to win cash" or "Best expected cash" across the whole list.

## Filters

- **Cost**: show all, free only, or only those with a registration / entry fee (a fee mentioned on any site that lists the hackathon counts)
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
