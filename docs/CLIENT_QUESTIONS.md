# SiteForge AI — Questions for Client Confirmation

These questions settle the decisions that affect architecture, cost, timeline and risk.
Each question shows what the platform does today, so you can confirm it or tell us what to change.

**How to answer:** a short answer per question is enough. Mark anything you're unsure about with **"?"** and we'll propose a default.

---

## A. Business goals and scope

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| A1 | What is the business purpose of the ~200 websites? (lead generation, affiliate/content sites, client sites, e-commerce, a portfolio of brands, something else) | Affects content strategy, SEO approach and monetisation features | Content and lead-generation sites |
| A2 | Who owns the websites: you, your clients, or end users of a SaaS you'll sell? | Decides between single-tenant and multi-tenant design, billing and isolation | Single organisation (you) |
| A3 | Is 200 the launch target or the long-term ceiling? How many sites per month do you expect to create? | Sets queue sizing, server count and AI budget | 200 active sites, extendable to 1,000 |
| A4 | Do you need a target launch date for milestone 1 (one site from one instruction, end to end)? | Planning and phasing | Phases 1–10 as in the spec |
| A5 | What does "success" mean commercially (traffic, revenue, number of live sites, time saved)? | Lets us prioritise which features to build first | Number of reliable live sites |
| A6 | Will other people (staff, clients, freelancers) use the dashboard? Roughly how many? | User management, roles and permissions | Admin / operator / viewer roles |

## B. Website creation workflow

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| B1 | Should websites be created from short text commands, uploaded briefs (PDF/DOCX), or both? | Input workflow and parsing | Text commands |
| B2 | Should we support bulk creation (e.g. a CSV of 50 topics)? | Batch queueing and cost controls | One site per request |
| B3 | ~~Should the AI choose the technology, or must a user choose?~~ **Confirmed: the user selects the technology.** | Framework-selection logic | User must pick; AI shows a suggestion only |
| B4 | Which pages must every site have? (Home, About, Services, Blog, FAQ, Contact, Legal pages…) | Templates and sitemap generation | Home, About, Offer, Journal, FAQ, Contact |
| B5 | Do sites need legal pages (privacy policy, cookie banner, terms, imprint)? In which countries? | Compliance (GDPR, ePrivacy, etc.) | Not generated yet |
| B6 | ~~Go live automatically or wait for approval?~~ **Confirmed: online automatically.** | Deployment controls | Published as soon as the quality checks pass |
| B7 | After launch, should sites keep receiving new AI content (e.g. two articles a week)? | Scheduled content jobs and AI cost | Manual "New content" action only |
| B8 | Do you have your own design templates or brand guidelines that generated sites must follow? | Template system and design control | AI-generated brand per site |
| B9 | Are there industries or topics we must refuse (medical, financial advice, adult, gambling…)? | Content policy and legal risk | No restrictions configured |

## C. Technology and frameworks

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| C1 | What share of the 200 sites will be WordPress / Next.js / Shopify / Laravel? | Which adapters to finish first | Next.js first, then WordPress |
| C2 | For WordPress: which plugins are mandatory (SEO, forms, caching, security, page builder)? | Provisioning scripts and maintenance | Theme + WP-CLI import only |
| C3 | For WordPress: should editors use Gutenberg, a page builder (Elementor, etc.), or only the AI? | Theme architecture | Classic custom theme |
| C4 | Must every site have an admin panel or CMS for non-technical editing? | Generated architecture per stack | Only WordPress/Shopify have a CMS |
| C5 | For Laravel: what "business application" features are expected (accounts, bookings, payments, dashboards)? | Scope of the Laravel generator, which can grow very large | Content pages + contact form |
| C6 | Which other frameworks matter later (Astro, Django, Webflow, Wix, Ghost…)? | Adapter roadmap | Astro and Django planned |
| C7 | Should generated source code be stored in Git (GitHub/GitLab), one repository per site? | Version control, CI/CD and handover | Stored on the platform server only |

## D. Shopify and e-commerce — **Confirmed: no Shopify** (section kept for reference)

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| D1 | Should Shopify stores be created automatically, or will you create each store and connect it? Shopify does not offer fully automatic creation of normal stores through its API. | Feasibility: Partner/Plus programmes are needed for automatic store creation | You create the store, we connect it with an Admin API token |
| D2 | Where do products come from: AI-generated, a supplier feed, CSV, or dropshipping apps? | Catalogue import pipeline | AI-generated draft products |
| D3 | Should products be published or stay as drafts until reviewed? | Risk of wrong prices or descriptions going live | Drafts |
| D4 | Do you need payments, shipping, taxes and inventory configured automatically? | Many of these settings can't be changed through the API, or need a manual step | Not configured |

## E. Domains and DNS

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| E1 | ~~Buy new domains or connect existing ones?~~ **Confirmed: buy new domains through the Cloudflare or OVH API.** | Registrar integrations and payment flow | Implemented: live search with prices, purchase, auto-renew; existing domains still supported |
| E2 | What is the maximum price per domain, and should an admin confirm each purchase or should it be fully automatic? | Financial controls | Cap 50 per domain; admin confirms each purchase (one setting to make it automatic) |
| E3 | Which registrars hold your domains today (Cloudflare, OVH, Hostinger, GoDaddy, Namecheap…)? | Which adapters to build | Cloudflare and OVH DNS |
| E4 | ~~Who chooses the domain provider?~~ **Confirmed: the user selects the domain provider per website.** Which providers must be available at launch (Cloudflare, OVH, Hostinger, others)? | Adapter priority | User picks Cloudflare, OVH or "platform URL only"; Hostinger planned |
| E5 | You mentioned "three websites per Cloudflare account". Which plan is that based on? Can we see the account? | This is not a standard Cloudflare free-plan limit; we need to check it before designing around it | Per-account site limit is configurable |
| E6 | Can sites use subdomains (topic.yourbrand.com), or does each site need its own domain? | Cost, SEO and DNS automation | Platform URL or custom domain |
| E7 | Should domain auto-renewal be on? Who gets expiry alerts? | Avoids losing domains | Expiry is monitored; renewal is not automated |

## F. Hosting and infrastructure

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| F1 | Should hosting be picked automatically or configured manually per site? | Provisioning logic | Selected per site |
| F2 | Do sites need separate servers or IP addresses, or can they share secure infrastructure? Is there a specific reason (SEO footprint, client isolation, compliance)? | Biggest driver of hosting cost: 200 servers vs. a few shared ones | Shared hosts, each site in its own container or directory |
| F3 | Which hosting accounts exist today (Hetzner, OVH, Hostinger…)? Which plans and regions? | Adapter priority and capacity planning | Hetzner Cloud + Docker/Traefik |
| F4 | What is the monthly infrastructure budget? | Server sizing and concurrency | Not set |
| F5 | Where should the central platform run (your server, our server, cloud)? Who maintains it? | Operations and responsibility | Docker Compose on one server |
| F6 | Do you need a CDN, or only for some sites? | Performance and cost | Cloudflare proxy when Cloudflare DNS is used |
| F7 | How long should backups be kept, and where (same provider, off-site, S3)? | Backup design and restore guarantees | Versioned deploy artefacts kept on disk |
| F8 | Are there data-residency requirements (EU only, for example)? | Region choice for servers and AI providers | None set |

## G. AI providers, content and images

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| G1 | Which AI text providers should be supported? Do you already have accounts or keys? | Integrations and billing | Anthropic Claude, with a built-in offline fallback |
| G2 | What is the AI budget per site, and per month in total? | Model choice, article counts and quotas | Not set |
| G3 | Which Fal.ai model and image style should be used? Is there a budget per image? | Image quality vs. cost | `fal-ai/flux/schnell`, with an SVG artwork fallback |
| G4 | Which languages are needed at launch, and later? | Multilingual content and SEO (hreflang) | English |
| G5 | How many articles per site at launch, and how long should they be? | Cost and time per job | 4 articles per site |
| G6 | Who reviews AI content before it is published: nobody, an editor, or only flagged items? | Review workflow and accountability | Automatic checks; flagged claims shown for review |
| G7 | How strict should the originality check be? Should duplicate content block publishing or only warn? | Quality gate behaviour | Warns below 60% unique |
| G8 | Do you need plagiarism or AI-detection services (Copyscape, Originality.ai)? | Third-party integrations and cost | Internal similarity check only |
| G9 | May generated images show realistic people? Are there image licensing rules? | Legal and brand risk | Fal.ai safety checker enabled |

## H. SEO and marketing

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| H1 | Do you have keyword research tools (Ahrefs, Semrush) the platform should use? | Data-driven SEO instead of AI guesses | AI and template keywords |
| H2 | Should sites be connected to Google Search Console, Analytics or Tag Manager automatically? | Extra OAuth integrations | Not connected |
| H3 | Should sites link to each other? Are there SEO "footprint" rules to follow (different IPs, themes, registrars)? | Affects isolation and template variety | Each site gets a unique brand and palette |
| H4 | Do you need newsletters, CRM or email integration for the contact forms? | Form handling and integrations | Form entries stored in the dashboard |

## I. Security, access and compliance

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| I1 | Which roles do you need beyond admin, operator and viewer? Should clients see only their own sites? | RBAC model | Three roles plus per-site members |
| I2 | Do you need single sign-on (Google Workspace, Microsoft) or two-factor login? | Authentication | Email and password with JWT |
| I3 | Who may approve infrastructure changes, DNS changes and spending? | Approval policy | Admins approve infrastructure; operators approve publishing |
| I4 | Should secrets live in a dedicated vault (HashiCorp Vault, AWS Secrets Manager) instead of the encrypted database? | Security posture | Fernet-encrypted in the database |
| I5 | How long must audit logs be kept? Are there compliance frameworks (GDPR, ISO 27001, SOC 2)? | Retention and controls | Kept indefinitely |
| I6 | Do generated sites collect personal data beyond the contact form? Do they need cookie consent? | GDPR obligations | Contact form only, no tracking scripts |

## J. Notifications, monitoring and maintenance

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| J1 | Where should alerts go: email, Slack, Teams, Telegram, SMS? Who receives which alerts? | Notification channels | In-app plus an optional webhook |
| J2 | What uptime is expected? What response time do you expect when a site goes down? | Monitoring interval and on-call setup | Checked every 60 s; auto-restart after 3 failures |
| J3 | Should dependency and security updates be applied automatically, or only recommended? | Maintenance risk vs. effort | Recommend only |
| J4 | Do you need monthly reports per site (traffic, uptime, content added)? | Reporting features | Dashboard only |

## K. Commercial and delivery

| # | Question | Why it matters | Current default |
|---|----------|----------------|-----------------|
| K1 | Is this an internal tool, or a product you will sell (white-label, subscriptions)? | Multi-tenancy, billing and branding | Internal tool |
| K2 | Who owns the platform code and the generated sites' code? | Licensing and handover | To be agreed |
| K3 | What support or SLA do you expect after delivery? | Maintenance contract | To be agreed |
| K4 | Can you give us test accounts (Cloudflare, Hetzner, OVH, Shopify dev store, Fal.ai, AI provider) for development? | Integrations can't be fully verified without real accounts | Needed before phases 6 and 9 |
| K5 | Are there existing websites or systems the platform must import or connect to? | Migration scope | None |

---

### Accounts and access we need from you to continue

1. An Anthropic API key, or another AI provider key, with a monthly spending limit
2. A Fal.ai API key
3. A Cloudflare API token (Zone:DNS:Edit) for one test domain
4. A Hetzner Cloud project API token, plus an SSH key name
5. A Shopify development store with an Admin API access token (if e-commerce is in scope)
6. OVH API application key, secret and consumer key (if OVH is used)
7. One test domain we can point at the platform
