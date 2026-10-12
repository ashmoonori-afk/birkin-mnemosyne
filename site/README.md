# Landing site

Static HTML and shared CSS, with no build step or runtime dependencies.
English is `/`; Korean is `/ko/`. The system color scheme selects light or dark.
Product text is sourced from the repository READMEs, CHANGELOG, release notes
and published results. Keep historical and current measurements separate.
The visual contract is [DESIGN.md](DESIGN.md).

From the repository root, preview locally:

```sh
python -m http.server 8000 --directory site
```

Open `http://localhost:8000/` and `http://localhost:8000/ko/`.
Check both at 390px and 1440px, in light and dark mode. Test locale links,
install anchors, keyboard focus, text zoom, external links, console errors
and navigation performance. The site must also work without JavaScript.

## Deployment

Vercel project: `birkin-mnemosyne`. Root directory: `site`.
Framework preset: Other. No build command. Output is the root directory.
Deploy from the **repository root**, not from `site/`, so the configured root
is applied once:

```sh
npx -y vercel@latest link --project birkin-mnemosyne
npx -y vercel@latest deploy --target=preview
```

Keep `.vercel/` local and untracked. Verify the preview, then follow the
[release checklist](../docs/releasing.md) and merge gates. After merge,
promote the already verified deployment:

```sh
npx -y vercel@latest promote <verified-preview-url>
```

Production: <https://birkin-mnemosyne.vercel.app/>.
Never promote a preview whose source differs from the merged content.
Keep Vercel's preview and production feedback toolbar disabled for this
project so it does not inject third-party scripts into the static pages.
Every release updates both README files, release notes and both site languages,
then verifies and redeploys the site.
