
# privacy-sweep

Discover where your personal data is listed and remove it — safely.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python pdr_scanner.py --query "Your Name, City ST, 555-123-4567, you@example.com"
```

## Safe discovery (recommended)
```bash
# Only open Google/Startpage results
python pdr_scanner.py --use-profile --sites google,startpage --open --limit-open 8 --no-open-non-google
```

## Print direct opt-out links for a group
```bash
python pdr_scanner.py --sites brokers_plus --optout
python pdr_scanner.py --sites more_people --optout --open-optout
```
