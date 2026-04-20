# How to apply for the elTOQUE API key

This is a one-time, manual step that **only the project owner can do**
— elTOQUE issues API keys to a contactable email address after a human
review. The form is in Spanish; this document gives you ready-to-paste
text and an explanation of every field, so you can fill it out cleanly
even if your Spanish is rusty.

Once the key is in your inbox, drop it into `.env` as
`ELTOQUE_API_KEY=…` and ping me and I'll wire `src/scraper/eltoque.py`
into the pipeline (it's the last open Phase 2 task, tracked as **2e**
in `MIGRATION.md`).

---

## Why we need it (and why we can't just scrape the site)

elTOQUE's TRMI (*Tasa Representativa del Mercado Informal*) — the
informal CUP/USD/EUR/MLC rate it publishes daily — is the most-watched
financial number in Cuba. The official BCC reference rate
(`SourceType.BCC_RATES`, already wired) sits at ~120 CUP/USD; the
elTOQUE rate runs ~525 CUP/USD. The gap between them is the single
most important macro indicator for anyone making investment, travel,
or remittance decisions about the island.

Direct HTML scraping of `eltoque.com` is **explicitly prohibited** in
their API terms — the relevant clause from the Spanish T&Cs is:

> *no se intenten extraer datos de las plataformas de elTOQUE por
> medios automatizados distintos a la API.*
> *("automated extraction of data from elTOQUE platforms by means
> other than the API is not permitted.")*

Their answer is the public dev API, which they made specifically so
third-party developers can stop scraping them. We use the API.

---

## Step 1 — Open the application page

Go to either of these (they redirect to the same form-embedded
article):

- <https://eltoque.com/eltoque-abre-acceso-a-su-api-de-las-tasas-de-cambio>
- <https://dev.eltoque.com/eltoque-abre-acceso-a-su-api-de-las-tasas-de-cambio>

The article title is **"elTOQUE abre acceso a su API de las Tasas de
cambio"**. Scroll past the article body until you see an embedded form
(it's a Google Form / Typeform-style block).

If the form isn't visible (some ad-blockers hide embedded Google
Forms), disable shields for `eltoque.com` and reload.

> **Tip:** the page also has an "Idioma / Language" toggle (top right).
> Switching to English changes most of the article copy but **does
> not translate the form itself** — the form fields are always in
> Spanish. Use the cheat-sheet below.

---

## Step 2 — Fill in the form (cheat-sheet)

Form fields vary slightly over time as elTOQUE iterates the dev
program. Below is what you'll most likely see, with a Spanish
suggested answer for each. **Copy the Spanish text on the right
verbatim** — elTOQUE's review team is small and giving them clear,
non-promotional Spanish answers gets you approved fastest.

| Field (Spanish) | What it's asking | Suggested answer (paste this) |
|---|---|---|
| **Nombre completo** | Your legal name | *(your real name)* |
| **Correo electrónico** | Email — **the API key arrives here** | *(your project email — use one you actually monitor; approval can take 1–4 weeks)* |
| **País** | Country | `Estados Unidos` |
| **Nombre de la aplicación o sistema** | App / project name | `Cuban Insights` |
| **URL de la aplicación o sitio web** | App / site URL | `https://cubaninsights.com` *(or your current domain — use whatever the app is publicly hosted at when you apply)* |
| **Tipo de aplicación** *(select)* | Type of app | `Sitio web informativo` *(if "news/information site" is an option) — otherwise pick the closest match: "Plataforma de análisis económico" or "Aplicación web"* |
| **¿Qué uso le dará a la TRMI?** | How you'll use the rate | *(see paste-ready paragraph below)* |
| **¿Cuál es el público objetivo de su aplicación?** | Target audience | `Inversionistas, viajeros y profesionales que siguen la economía cubana, principalmente desde Estados Unidos, Europa y América Latina.` |
| **Volumen estimado de peticiones por mes** | Estimated monthly request volume | `Aproximadamente 60 peticiones por mes (una por día, con caché de 24 horas).` |
| **¿Cómo conoció el servicio?** | How you heard about it | `A través del artículo "elTOQUE abre acceso a su API de las Tasas de cambio".` |
| **Acepto los Términos y condiciones de uso** *(checkbox)* | T&C consent | ✅ Check it. (See "What you're agreeing to" section below.) |

### Paste-ready: "¿Qué uso le dará a la TRMI?"

> Cuban Insights es un boletín diario y portal de análisis sobre la
> economía cubana, dirigido a inversionistas, viajeros y profesionales
> internacionales. Mostraremos la TRMI diaria de elTOQUE como una
> referencia clave del mercado informal de divisas en Cuba, junto con
> la tasa oficial del Banco Central de Cuba, en una sección dedicada
> de seguimiento cambiario y en informes diarios. Cada visualización
> incluirá el crédito visible "Fuente: elTOQUE" con enlace al sitio
> original, conforme a los Términos y condiciones de la API. Las
> peticiones serán bajas (aproximadamente una por día) gracias a una
> capa de caché de 24 horas.

(English gloss for your records: "Cuban Insights is a daily newsletter
and analysis site about the Cuban economy, aimed at international
investors, travelers and professionals. We'll display elTOQUE's daily
TRMI as a key reference for the informal FX market alongside the BCC
official rate, in a dedicated FX-tracking section and in daily
reports. Each display will include a visible 'Source: elTOQUE'
credit with a link, per the API T&Cs. Request volume will be low —
about one call per day — thanks to a 24-hour cache layer.")

---

## Step 3 — What you're agreeing to in the T&Cs

The full T&Cs are on the same page above the form. The clauses that
actually matter for your daily operation are:

1. **5,000 requests/month soft cap.** We need ~60. We're at <2% of the
   limit so this is irrelevant in practice, but it's why our scraper
   will cache aggressively (the code I'll ship pulls once per day,
   stores the snapshot, and serves the cached value for the rest of
   the day).
2. **Free during the beta.** elTOQUE reserves the right to introduce
   pricing later; if/when they do we'll need to renegotiate or add a
   billing entry to `render.yaml`. For now, no card.
3. **Must cite elTOQUE on any page that displays the number.** The
   `report.html.j2` footer already credits elTOQUE; we'll add a
   visible credit + outbound link on the FX-specific tool page in
   Phase 5.
4. **API keys are personal.** You can't share or republish the key.
   Treat it like a password: only in `.env`, never committed.
5. **Don't editorialize using only the elTOQUE rate as
   evidence of policy claims.** The clause specifically warns against
   misusing the rate for partisan or anti-government framing. Our
   editorial voice is analytical (investment-research register), not
   activist, so this is a non-issue — but worth being aware of when
   we write headline copy.
6. **No racial / discriminatory uses.** Standard ethics clause; not
   relevant.

---

## Step 4 — Wait for approval

- elTOQUE reviews applications **manually**.
- Typical turnaround in the public beta: **1 to 4 weeks**. (They've
  acknowledged in past posts that the dev team is small.)
- The key arrives by email from a `@eltoque.com` or `@dev.eltoque.com`
  address. Check spam.
- If you've heard nothing in 4 weeks, the cleanest follow-up is to
  reply to the article on the same page (their devs read comments) or
  email `contacto@eltoque.com` with subject "Seguimiento solicitud
  API Tasas — Cuban Insights". I can draft that follow-up email in
  Spanish if/when we hit that point.

---

## Step 5 — When the key arrives

1. Open `.env` (NOT committed to git — already in `.gitignore`).
2. Add this line (replace the placeholder with the actual key):

   ```
   ELTOQUE_API_KEY=tk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

3. Add the same key to Render via the dashboard:
   *Cuban Insights → Environment → Add Environment Variable*. The cron
   services (`cij-daily-pipeline`, `cij-weekly-climate`) inherit from
   the same group, so adding it once covers all three services.
4. Tell me. I'll then:
   - Add `eltoque_api_key: str = ""` to `src/config.py`.
   - Build `src/scraper/eltoque.py` against
     `https://tasas.eltoque.com/v1/trmi` with header
     `Authorization: Bearer <key>` (the exact endpoint shape ships in
     the welcome email — I'll match it then).
   - Wire `EltoqueScraper` into `src/pipeline.py` next to the BCC
     scraper.
   - Add the visible "Source: elTOQUE" credit to the FX page when
     Phase 5 lands.
   - Mark **2e** complete in `MIGRATION.md`.

---

## What if elTOQUE rejects the application?

Rare but possible. If it happens:

- They'll email you the rejection reason. Forward it to me and I'll
  draft a Spanish appeal.
- Until/unless we get a key, the FX tooling will run on the BCC
  official rate alone. The report templates degrade gracefully
  (`{% if eltoque_rate %}…{% endif %}`-style) so a missing TRMI just
  removes one comparison line from the daily briefing — nothing
  breaks.
