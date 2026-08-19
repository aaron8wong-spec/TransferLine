# TransferLine

Static prototype: a California community college transfer articulation finder.

- `index.html` — landing page
- `finder.html` — the three-step finder (Colleges / Records / Results)
- `support.js` — the component runtime both pages load
- `_ds/` — design-system stylesheet and bundle

Articulation data in the finder is **hard-coded sample data**, not real ASSIST agreements.

## Run locally

    python3 -m http.server 8000
    # http://localhost:8000

## Deploy on Vercel

No build step — this is plain static HTML.

1. Push this folder to GitHub (see below).
2. On vercel.com: **Add New… → Project**, import the repo.
3. Framework Preset: **Other**. Build Command: leave empty. Output Directory: `.`
   (If the repo root is the parent of this folder, set **Root Directory** to `deploy`.)
4. Deploy. Vercel serves `index.html` at the domain root.

Vercel CLI alternative, from inside this folder:

    npx vercel        # preview deploy
    npx vercel --prod # production

## Push to GitHub

    git init -b main
    git add .
    git commit -m "TransferLine prototype"
    git remote add origin https://github.com/aaron8wong-spec/TransferLine.git
    git push -u --force origin main
