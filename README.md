# Cooking with the Lorax

Lori Weischedel's private-chef business, from one Django app (built like `meal_planner`, with Claude) on two hostnames:

- **`https://cookingwiththe.loraxglobal.com`**: the public website for customers and Google Ads (Home, About,
  Services, Gallery, Contact, Privacy). Client menu and household links (`/m/…`, `/h/…`) and photos also live here.
- **`https://chef.cookingwiththe.loraxglobal.com`**: Lori's signed-in workspace. It is kept out of search engines
  (`X-Robots-Tag: noindex`).

`kitchen.middleware.HostRoutingMiddleware` picks the URLs by host: the public host uses `lorax/urls_public.py`, and
any other host uses `lorax/urls.py`. If a workspace path such as `/recipes/` is opened on the public host, it
redirects to the same path on `chef.`, so old bookmarks keep working.

## What it does

- **Clients (households)**: contacts (who gets menus), dated notes (pin the important ones), and
  preferences. Each preference option gets a stance: loves, likes, avoids, or allergy/never.
- **Recipes**: import from a web address, from photos (cookbook page, recipe card, screenshot), or
  from pasted text. Claude reads the recipe into ingredients and steps, and it opens in the editor for
  review. Recipes can also be typed in by hand. The servings box on a recipe scales every amount.
- **Menus**: a meal plan for one household, made of dishes (a recipe, a date, a course and the number
  of servings). Dishes can have their own title, description or photo for that menu.
- **Sending menus**: a formatted email to the household's contacts, linking to a private menu page.
  Clients approve the menu or leave notes there without signing in. Responses show up on the home page
  and in the Clients tab.
- **Client page**: one private link per household that lists every menu they've been sent.
- **Shopping lists**: built per menu. Ingredients are scaled to each dish's servings, added up across
  dishes and grouped by store section. Items tick off on a phone, and extra items can be added by hand.
- **Dish photos**: Lori's own photos, stored in the database and used on menus and in emails.
- **Website page** (`/website/`): inquiries from the contact form (each is also emailed to the business contact
  email, with Reply-To set to the visitor), the services list, the website text, and Google tag / Ads conversion
  IDs. A photo appears in the public gallery when “Show on website” is ticked on it. The first gallery photo is the
  home page's hero image.
- **Admin page** (`/admin/`): preference options, business details shown to clients, and which
  Google accounts can sign in. `/django-admin/` is the raw database admin for troubleshooting.

Sign-in is Google only, for accounts on the allow list. `lweischedel@gmail.com`,
`lori@loraxglobal.com` and `michael@carrell.us` are seeded as admins (`INITIAL_ADMIN_EMAILS`); others are added on the Admin page.

Client links (`/m/<token>/`, `/h/<token>/`) and photo URLs (`/photo/<token>/`) are unguessable and
need no sign-in. Anyone with a link can view the page and, for menus, respond.

## Setup

1. **Database**: the `cooking_with_the_lorax` database on the home Postgres server (`192.168.68.78`),
   same login as `meal_planner`. Migrations run when the container starts.
2. **Environment**: set these in the Portainer stack's environment variables (Portainer writes them to
   `stack.env`). For a local `docker compose up`, put them in `stack.env` here. Never commit it.
   - `SECRET_KEY`: a new random value
   - `PUBLIC_BASE_URL`: `https://cookingwiththe.loraxglobal.com` (default; the old name `APP_BASE_URL` also works)
   - `CHEF_BASE_URL`: `https://chef.cookingwiththe.loraxglobal.com` (default)
   - `DB_HOST`, `DB_USER`, `DB_PASSWORD`: same as `meal_planner`; `DB_NAME=cooking_with_the_lorax`
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: the OAuth client `meal_planner` uses works. Add
     `https://chef.cookingwiththe.loraxglobal.com/accounts/google/login/callback/` to its authorized
     redirect URIs (sign-in happens on the workspace host).
   - `ANTHROPIC_API_KEY`; optionally `CLAUDE_MODEL` (default `claude-opus-5-5`)
   - `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`: Gmail SMTP with an app password (same as `meal_planner`)
   - Optional: `DEFAULT_FROM_EMAIL` (default `Cooking with the Lorax <meals@carrell.us>`, which must be
     an address the SMTP account can send as), `MENU_REPLY_TO`, `INITIAL_ADMIN_EMAILS`, `TIME_ZONE`
3. **Network**: the container listens on host port 8010 and joins the `proxy` network as
   `cooking_with_the_lorax`.
   - GoDaddy DNS for loraxglobal.com: CNAME `cookingwiththe` → `@` and CNAME `chef.cookingwiththe` → `@`
   - Nginx Proxy Manager: one proxy host with both domain names, `cookingwiththe.loraxglobal.com` and
     `chef.cookingwiththe.loraxglobal.com` → `192.168.68.78:8010`, with Let's Encrypt (one certificate for both)
     and Force SSL
   - Pi-hole: CNAMEs for both names → `server.carrell.us`, so they work from home
4. **Deploy**: as a git-backed Portainer stack (this repo), or `docker compose up -d --build` here.

## How the recipe importer works

`kitchen/importer.py`. A web page is fetched by the app first, and Claude reads its schema.org recipe
data and text. Only public addresses are fetched, and each redirect is checked. If the site refuses
the request, Claude fetches the page itself with its web fetch tool. Photos are scaled to 2000px and
sent as images. The result is structured output (`RecipeDraft`), saved as a recipe and opened in the
editor. Server-side refusal fallback is on (`fallbacks: "default"`).

## Tests

Tests run on the home Postgres server, in a throwaway `test_cooking_with_the_lorax` database that
Django creates and drops (the `DB_USER` needs permission to create databases). Claude, the web and
email are mocked.

```bash
docker compose run --rm cooking_with_the_lorax python manage.py test kitchen
```
