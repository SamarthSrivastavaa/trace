# Razorpay AI Buildathon 2026 — Reference Facts

Compiled 2–3 September 2026. Facts about the event and its ecosystem only.
No project ideas, no product design, no recommendations.

**Classification used throughout:**

| Tag | Meaning |
|---|---|
| `[VERIFIED]` | Directly from a primary source (razorpay.com, the application form, official docs, Razorpay's own repos/blog, a government source) |
| `[REPORTED]` | Consistent secondary reporting; not confirmed on a primary source |
| `[MEASURED]` | Produced by my own query/analysis; methodology stated |
| `[INFERENCE]` | Reasoned from evidence, not stated anywhere |
| `[UNKNOWN]` | Insufficient evidence |

---

## 1. What the event actually is

| Item | Detail | Class |
|---|---|---|
| Name | Razorpay AI Buildathon | `[VERIFIED]` |
| URL | https://razorpay.com/buildathon/ | `[VERIFIED]` |
| Nature | **Not a prize hackathon.** It is a hiring funnel that uses a build as the screen | `[VERIFIED]` |
| Reward | AI Builder Internship — **₹75,000/month**, 6 or 12 months at the candidate's choice | `[VERIFIED]` |
| Location | In person, Bangalore, "from September" | `[VERIFIED]` |
| Eligibility | Students only; graduation year options on the form are **2027 / 2028 / 2029** | `[VERIFIED]` |
| Programmes | B.Tech, M.Tech, BCA, MCA or equivalent technical programmes | `[REPORTED]` |
| Number of offers | Not stated anywhere | `[UNKNOWN]` |
| Who reviews submissions | Not stated anywhere | `[UNKNOWN]` |
| Ranking vs threshold | No language implying a leaderboard; "if it has signal we call you in" reads as a threshold | `[INFERENCE]` |

### Process — verbatim from the official page

> "Four steps: pick a track, build something real, show your work (a public repo, a 5 minute pitch video, the architecture), and if it has signal we call you in."

`[VERIFIED]`

Additional process detail: no aptitude test, no screening call, no group discussion; next stage after screening is a technical panel interview. `[REPORTED]`

### Submission requirements

- A **public repository** `[VERIFIED]`
- A **5-minute pitch video** (may be unlisted) `[VERIFIED]` / unlisted detail `[REPORTED]`
- The **architecture** / architecture walkthrough `[VERIFIED]`
- Expected to be able to explain: the problem chosen, why it matters, how the solution works, the tech used, key technical decisions, **what went wrong and how it was fixed** `[REPORTED]`

### Application form

Linked from the official page: `https://forms.gle/d9r2gvxp8cmoZhon9`
(redirects to `docs.google.com/forms/d/e/1FAIpQLScJ9XSqVCB2oaPwEMH0Zk3I1OpILFW1WpWdWweQ2950jdRzlg/viewform`)

Page one asks exactly five required questions: `[VERIFIED]`

1. Email
2. Full Name
3. College Name
4. Graduation Year — options 2027, 2028, 2029
5. In-person internship availability starting September — Yes / No

**The form collects no repository, no track, no video.** `[VERIFIED]` for page one.
Whether a second page exists is `[UNKNOWN]` — a paginated Google Form exposes only its first section to an unauthenticated fetch. **Worth checking in a browser.**

Where the build is actually submitted is `[UNKNOWN]`.

### Deadline

**5 September 2026**, reported consistently by multiple independent aggregators as the *application* deadline. `[REPORTED]`

Two separate fetches of the official page surfaced **no date at all** — no deadline, no FAQ, no evaluator info, no headcount. `[VERIFIED]` that these are absent from the page.

---

## 2. Judging criteria

Four stated evaluation parameters:

| Criterion | Stated meaning |
|---|---|
| **Problem taste** | Did the participant pick something that actually matters? A meaningful real-world financial or merchant problem |
| **Build quality** | Does it run? Is it structured? **Would you trust it?** Clean repo structure, execution reliability |
| **AI judgment** | Was AI used in the right place? Did the participant correctly identify places where AI should **not** be used? Forcing an LLM where a rule-based system is better is marked down |
| **Failure recovery** | **"What broke, and how you got out?"** — what broke during development and how it was resolved |

Also attributed to the organiser: *"We read the work, not the resume."*

**Classification caveat:** these are stated in the event brief and corroborated by four independent aggregators, but **two separate fetches of the official page did not surface them**. Most likely a fetch-summarisation artifact rather than their absence. Treat as `[REPORTED]`, near-certain, but not personally verified on the primary page.

---

## 3. The five tracks

Track "bars" below are **verbatim** from razorpay.com/buildathon. `[VERIFIED]`

### Track 01 — AI Growth & Agentic Commerce

- **Objective:** Grow a merchant's revenue and/or make them transactable by AI buyers.
- **Build requirement:** an agent that **either** (A) grows revenue for a merchant using Razorpay test-mode APIs, **or** (B) **makes a merchant transactable by an AI buyer end-to-end**.
- **The bar:** *"Every money action explainable, bounded and gated. Show the audit trail and one failure handled gracefully."*
- **Context named in the brief:** NPCI UAP, agentic commerce, ACP, AP2, x402, Razorpay's in-app pilots.
- **Example directions given:** conversational in-app checkout, agent-readable catalog, upsell/cross-sell agent, campaign orchestrator.

### Track 02 — AI Risk Manager

- **Objective:** Stop merchants losing money to fraud, returns, chargebacks.
- **Build requirement:** a working detector, verifier, **or** auto-responder for one class of financial loss.
- **Mandatory evidence:** measure **precision and recall on a held-out test set**.
- **The bar:** *"Honest metrics including false-positive cost. Strictly defense-only: anything offense-capable is disqualified."*
- **Example directions given:** chargeback evidence responder, return-risk scorer, fraud-spike detector, abuse-ring sentinel.

### Track 03 — AI Revenue Recovery

- **Objective:** Find revenue that is slipping away and win it back.
- **Build requirement:** an agent that (1) detects revenue at risk, (2) determines the appropriate intervention, (3) executes a bounded recovery workflow.
- **The bar:** *"Don't just identify the problem. Show measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail."*
- **Areas named:** payment failures, checkout abandonment, overdue receivables, subscription failures, mandate failures.
- **Example directions given:** payment degradation → root cause → recovery action; checkout drop-off recovery; failed-subscription recovery; B2B receivables chaser; mandate retry sequencer; Hinglish voice recovery; promise-to-pay tracker.

### Track 04 — AI Finance Controller

- **Objective:** Run the books and cash position.
- **Build requirement:** an agent that closes one finance-operations loop across **at least 50 records** of synthetic data.
- **Mandatory reporting:** match rate, and the exceptions it could not resolve.
- **The bar:** *"Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."*
- **Context in the brief:** verification capacity is a major bottleneck; reconciliation, settlement and forecasting remain heavily manual.
- **Example directions given:** multi-source reconciliation, settlement Q&A agent, forward cash forecaster, tax-line matcher.

### Track 05 — Open Track

- **Objective:** Build what you believe should exist. Any domain, workflow or user.
- **The bar:** *"Show a real problem, a working product, meaningful use of AI, and evidence that it creates value."*
- **Organiser guidance:** surprise us; solve a problem you deeply understand; build something they have not thought of.

---

## 4. Razorpay strategic context

### 4.1 Agent Studio — launched 12 March 2026 `[VERIFIED]`

- Announced at Razorpay's **FTX'26** event in India.
- **Built on Anthropic's Claude Agent SDK.**
- Described as a B2B agent marketplace and builder platform for payments and business banking.
- Runs natively inside Razorpay's payment infrastructure with access to transaction data, settlement records, customer activity signals, and third-party tools (Shopify, Tally, QuickBooks, WhatsApp, Slack, Shiprocket).
- Also launched: an **Agentic Experience Platform**.

**Agents listed on the product page:**

1. Dispute Responder — "Auto-responds to chargebacks with optimized evidence to maximize dispute win rates"
2. Subscription Recovery — analyses failed subscription payments, retry logic, customer nudges
3. Abandoned Cart Conversion — re-engages via WhatsApp/email with personalised nudges and offers
4. RTO Shield — detects high-risk COD orders pre-dispatch using address validation and pincode intelligence
5. RTO Insights — return patterns across pincodes, products, customers
6. Settlement Insights — daily settlement summaries via WhatsApp
7. Cashflow Forecaster — "Predicts cash position 3–7 days ahead with alerts for payroll risk, shortfalls, and payout failures"

> **Note the overlap with the track list.** Tracks 02, 03 and 04's example directions map closely onto shipped Agent Studio agents. `[INFERENCE]`

### 4.2 Agent Studio public guardrails `[VERIFIED]`

From Razorpay's "Agent Studio: Principles, Guardrails, and Merchant Control" post:

- Merchants "review and approve exactly what data the agent can access, what actions it can take, and where it needs human approval."
- Sensitive operations: "agents escalate to the merchant — typically on WhatsApp — rather than acting unilaterally."
- "Review-first mode": agents prepare work and hold it for merchant sign-off.
- **"No agent takes an irreversible action without explicit merchant approval."**
- "The merchant can turn off any agent at any time. One tap. Immediate."
- Discounts: agents work only within the "merchant's existing discount and coupon configuration"; they do "not create new discounts, modify pricing, or decide independently how much to offer."
- **Dark patterns:** agents "must not employ dark patterns" per India's 2023 Guidelines, including false urgency, confirm shaming, and manufactured scarcity. **"While agents can communicate genuine time-bound offers, the agent will not fabricate urgency."**
- Opt-out: "Customers who opt out are permanently suppressed — no exceptions." / "A no is a no."
- **Platform-level validation** covering: compliance boundaries, **amount verification**, PII handling, scope checks.
- "Out-of-scope behavior detection" blocks unintended actions.
- Full audit trail via performance dashboards.
- **Pre-launch certification** reviewing logic, data scope, compliance, communication patterns.
- Post-launch: "Agent communication patterns are monitored continuously"; problematic agents can be removed.

Not specified in that document: enforcement timelines, penalties, third-party appeal, monitoring efficacy data. `[VERIFIED]` as absent.

The Agent Studio **product page** mentions no guardrails, approval workflows or compliance content at all. `[VERIFIED]`

### 4.3 Public criticism of Agent Studio `[REPORTED]`

Raised by Indian tech press (Medianama and others) in March 2026:

- **Dark patterns risk** — agents doing subscription recovery and cart conversion use "personalised nudges" and "offers" via WhatsApp/email. At the launch event, an agent reportedly pressed Razorpay's own CEO toward an impulsive purchase with a steep discount and a 24-hour deadline.
- **Price discrimination** — steep discounts to some customers and not others.
- **Hallucination** — a dispute agent optimised for "maximising dispute win rates" may produce false outputs.
- **Pricing opacity** — unclear whether Agent Studio is free to merchants.
- **Regulatory gap** — no dedicated agentic-AI regulation; platforms define their own terms.

Razorpay's CPO publicly responded on pricing and compliance concerns.

### 4.4 Agentic payments with NPCI `[VERIFIED]`

- **20 February 2026** — Razorpay and NPCI announced Agentic Payments on **Claude**, at the India AI Impact Summit, New Delhi. Pilot phase with a select group of users. Merchants live: **Zomato, Swiggy, Zepto**.
- Earlier equivalent shipped with **OpenAI / ChatGPT**, announced at Global Fintech Fest, with banking partners **Axis Bank** and **Airtel Payments Bank**.
- Built on **UPI Reserve Pay** — NPCI mandate infrastructure letting a user authorise a single spending limit per merchant, enabling subsequent transactions without per-transaction PIN/OTP.
- Also referenced: **UPI Circle**.
- Stated design: one-time consent-based authorisation, per-merchant spending caps, full visibility, instant revocation.
- Razorpay's framing of the problem solved: the "human-in-the-loop" authentication friction that forced users out of conversational flows.
- Also announced: Razorpay + **Sarvam AI** agent-powered payments (Indus app).

**NPCI Unified Agent Protocol (UAP)** — reported as likely to be unveiled at Global Fintech Fest 2026, Mumbai. Intended to let users delegate payment authority to AI agents within a pre-set limit, leveraging UPI Circle and Reserve Pay. `[REPORTED]` — **not publicly specified enough to build against.**

### 4.5 Razorpay Engineering's own AI publications `[VERIFIED]`

A consistent narrative template across three posts — *manual hours eliminated → automated, with a stated accuracy delta*:

| System | Result |
|---|---|
| **Bumblebee** — multi-agent merchant-risk / fraud detection | Flags risky merchants in **under 90 seconds**. Replaced ~**700–800 human hours/month** (10,000–12,000 manual website reviews/month at ~4 min each). Accuracy **88% → over 99%** |
| **Project Viveka** — oncall agent (Apr 2026) | "From 30-Minute Investigations to 90-Second AI Analysis" |
| **AI-powered security triage** (Jun 2026) | "From 750 Hours to 2 Hours" |

Bumblebee architecture as described: an orchestrator delegating to specialised sub-agents, each covering a different dimension of merchant risk (website content, domain registration red flags, fake social media profiles) — modelled on how the human risk team specialised and then compared notes.

Engineering blog: `engineering.razorpay.com` (Medium-hosted; returns 403 to automated fetch). Also `dev.to/razorpaytech`.

---

## 5. Technical resources

### 5.1 Razorpay MCP Server `[VERIFIED]`

- Official: `github.com/razorpay/razorpay-mcp-server`; docs at `razorpay.com/docs/developer-tools/mcp-server/`
- **35+ tools** across payments, orders (including **mandate orders**), payment links, settlements
- Test mode auto-detected from key prefix: `rzp_test_` vs `rzp_live_`
- Two deployment modes: **Remote MCP Server** hosted by Razorpay (recommended, no setup), and a **local self-hosted** Docker option
- Works with Claude Desktop, Cursor, VS Code (MCP extension), other MCP-compatible tools
- Also listed in the Docker MCP Catalog and PulseMCP

### 5.2 Webhook semantics — from Razorpay's own docs `[VERIFIED]`

These are stated guarantees, not assumptions:

- **At-least-once delivery** — "you may receive the same event multiple times"
- Duplicates identified via the **`x-razorpay-event-id`** header, unique per event
- **Out-of-order delivery** — "you may not always receive the webhooks in the order… configure your webhook URL to not expect delivery of these events in this order"
- Handlers must return **2xx within 5 seconds**; otherwise treated as failure
- On failure, retried at progressive intervals per an **exponential back-off policy, for 24 hours**
- Best practice stated: **implement idempotency**; verify the webhook signature

Docs: `razorpay.com/docs/webhooks/`, `/webhooks/best-practices/`, `/webhooks/validate-test/`, `/webhooks/faqs/`

### 5.3 Razorpay open-source plugins `[VERIFIED]`

Public repos under `github.com/razorpay`, all PHP:

| Repo | Commits (as of 2 Sep 2026) | First commit |
|---|---|---|
| `razorpay-magento` | 563 | 2016-03-16 |
| `razorpay-woocommerce` | 1,576 | 2015-02-17 |
| `razorpay-prestashop` | 193 | 2015-06-09 |

Also: `razorpay-whmcs`, `razorpay-mcp-server`, and others.

**Duplicate-order / race-condition history** (searched by commit message across all refs):

| Repo | Commit | Date | Subject |
|---|---|---|---|
| magento | `e9f3279` | 2017-03-27 | Fixing double order creation (#49) |
| magento | `bd8d577` | 2017-06-02 | [double order] Magento double order fix (#56) |
| magento | `53e1e27` | 2020-03-24 | SI-1187: fixed issue related with webhook processing duplicate order |
| magento | `1d5243f` | 2020-07-02 | Fix webhook duplicate order (#181) |
| magento | `31e2789` | 2020-07-06 | Fix webhook duplicate order (#182) |
| magento | `96a0040` | 2020-12-09 | Added delay in webhook to avoid duplicate orders (#212) |
| magento | `c3ad921` | 2021-01-27 | added wait time for webhook to execute, to avoid duplicate orders |
| magento | `ecef728` | 2021-03-01 | PON-970: fixed duplicate quote entry |
| magento | `5d1a2b3` | 2023-08-16 | Added 1 second delay to order.paid webhook |
| magento | `1f509f8` | 2023-08-24 | Added delay to webhook |
| magento | `a8ecd58` | 2023-08-25 | Changed delay |
| magento | `eea70e1` | 2024-08-20 | Added quote inactive logic |
| magento | `b12d671` | 2024-07-05 | Order placement cron job in case of callback fails |
| woocommerce | `5447232` | 2022-07-06 | Fixed duplicate Order ID issue in order.php using order ID from transient |
| woocommerce | `7446d06` | 2022-07-06 | Added delay of 5 minutes before initiating webhook process |
| woocommerce | `127bc0c` | 2022-08-03 | fix duplicate wooorderid and change amt validation |
| woocommerce | `34ca957` | 2023-02-08 | added session value to remove duplicate orderid bug |
| woocommerce | `e8ff6ee` / `4f766ed` | 2026-01 | added lock to avoid multiple api call on plugin_loaded hook / release lock |
| woocommerce | `a57dfd6` | 2026-06-12 | fix: address sync cron — fix null checkpoint and completion race |
| prestashop | `8b3c10f` | 2021-06-11 | Merge PR #66 from `razorpay/fix_webhook_duplicate` |

**Related public issues:** `razorpay-magento#208` "Order duplication issue when webhook is enabled", `#291` "Orders getting duplicated", `#211` "Magento2 Duplicate Order Issue", `#179` "Payments Processed But Orders not Placed"; `razorpay-woocommerce#167` "Some Orders are twice entries and charged within seconds"; `razorpay-prestashop#64` "Orders not getting created in store but payment captured" (**open**); `razorpay-whmcs#93` (open).

**Other measured facts about these repos** `[MEASURED]`, by grep on current `master`:
- Searching `org:razorpay` issues for `idempoten` returns **0 results**
- **0 PHP files** across all three plugins contain the string `idempoten`
- **None** of the three reads `x-razorpay-event-id` (they read `HTTP_X_RAZORPAY_SIGNATURE` for auth only)
- `sleep(1)` is still present in `razorpay-magento/Controller/Payment/Webhook.php:249` on current master
- The guards that do exist are check-then-act on order status, without locks

### 5.4 Razorpay is actively making its own repos AI-legible `[VERIFIED]`

Present in the working trees:
- `razorpay-woocommerce`: `.agent/skills/add-webhook-handler.md`, `.ai/context/WEBHOOK_FLOW.md`, `.ai/diagrams/HLD_WEBHOOK_FLOW.md`, `.ai/diagrams/LLD_WEBHOOK_SEQUENCE.md`, `docs/flows/webhook-flow.md`
- Related PRs: `razorpay-woocommerce#650` "agentify codebase with LLM context docs and architecture diagrams"; `razorpay-prestashop#128` "Add agent readiness configuration for AI coding agents", `#129` "Agentify razorpay-prestashop with AI context documentation" (Apr 2026)

---

## 6. Agentic-commerce protocols named in the brief

| Protocol | Owner | What it is | Status |
|---|---|---|---|
| **AP2** (Agent Payments Protocol) | Google | Open, payment-method-agnostic protocol letting an agent **prove to a merchant that a human authorised a specific purchase**. Chains three cryptographically signed Verifiable Credentials: **Intent Mandate** (user delegates authority), **Cart Mandate** (user approves a specific cart at a specific price), **Payment Mandate** (derived credential the network sees). Docs: `ap2-protocol.org` | `[VERIFIED]` |
| **x402** | Coinbase | Revives HTTP status **402 Payment Required** for programmatic web payments. A payment *method* AP2 is designed to accommodate | `[VERIFIED]` |
| **ACP** (Agentic Commerce Protocol) | OpenAI / Stripe | Checkout layer | `[VERIFIED]` (named in the brief) |
| **TAP** (Trusted Agent Protocol) | Visa | **Agent identity** attestation to merchants — verifies *which agent*, complementary to AP2's *what was authorised* | `[VERIFIED]` |
| **UAP** (Unified Agent Protocol) | NPCI | India-specific delegation of payment authority on UPI rails | `[REPORTED]`, not publicly specified |

Ecosystem layering as commonly described: discovery (MCP) → agent-to-agent transport (A2A) → authorization (AP2 + TAP) → checkout (ACP, UCP) → settlement (card rails, real-time bank, x402 stablecoins).

**Note:** RFC 9396 (OAuth 2.0 **Rich Authorization Requests**, IETF Standards Track, May 2023) already standardises structured JSON `authorization_details` for fine-grained transaction consent — e.g. expressing a payment of an exact amount to an exact creditor — and is used in open banking. Relevant prior art for anything in the mandate/authorization space. `[VERIFIED]`

---

## 7. Indian regulatory context

### CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023 `[VERIFIED]`

- Issued by the **Central Consumer Protection Authority** on **30 November 2023**, notified under the **Consumer Protection Act, 2019**
- Enumerates **13 specified dark patterns**:
  1. False urgency
  2. Basket sneaking
  3. Confirm shaming
  4. Forced action
  5. Subscription trap
  6. Interface interference
  7. Bait and switch
  8. Drip pricing
  9. Disguised advertisement
  10. Nagging
  11. Trick wording
  12. SaaS billing
  13. Rogue malware
- Definition: practices in UI/UX "designed to mislead or trick users into doing an action they did not originally intend," subverting consumer autonomy, amounting to misleading advertisement, unfair trade practice, or violation of consumer rights under the CPA
- CCPA has since **advised e-commerce platforms to self-audit within 3 months** to detect and remove dark patterns, and has taken action against platforms

### Other Indian rails facts

- **NPCI circular OC-149 (June 2022)**: banks should keep Technical Decline (TD) **below 1%** `[REPORTED]`
- **NPCI publishes monthly, bank-wise BD/TD & uptime data** — approved %, business-declined %, technically-declined %, by issuer bank and by payer/payee PSP, from 2022 onward. Available via NPCI's UPI Ecosystem Statistics page and mirrored on India Data Portal / Dataful `[VERIFIED]` that the data is published
- **NPCI limits UPI AutoPay / e-mandate retry attempts per mandate cycle** — commonly cited as 3–4 attempts `[REPORTED]`, worth checking against the NPCI circular directly

---

## 8. Competitive field data

### Methodology

GitHub Search API, unauthenticated. Multiple semantically distinct query formulations, merged and deduplicated, filtered to repos created since 15 July 2026, classified by concept regexes over repo name + description — **not** by literal track labels.

Two samples were taken:
- **Fresh 10-query sweep (2 Sep):** 397 deduped repos
- **Merged all-query corpus:** 740 deduped repos

`total_count` for the single query `razorpay buildathon` was **613** on 2 Sep 2026.

**All figures are lower bounds.** Private repos, generically-named repos and unsubmitted work are invisible. Descriptions are a lossy proxy for contents.

### Field growth `[MEASURED]`

Repos created per day, 21 Aug – 2 Sep: 21, 38, 40, 34, 35, 26, 33, 49, 60, 81, 55, 67, 36.
Daily creation rate roughly **tripled** over that window.

### Conceptual cluster density (n=397) `[MEASURED]`

Clusters overlap; percentages exceed 100.

| Cluster | Count | % |
|---|---:|---:|
| Payment-failure recovery / retry / dunning | 128 | 32% |
| Agent authorization / mandate / intent gate | 79 | 19% |
| Reconciliation / settlement / finance controller | 62 | 15% |
| Shopping / checkout / storefront agent | 60 | 15% |
| Fraud / risk scoring | 56 | 14% |
| Graph / ring / collusion detection | 48 | 12% |
| Chargeback / dispute / RTO / returns | 27 | 7% |
| Voice / Hinglish / WhatsApp channel | 26 | 6% |
| Subscription / mandate lifecycle | 19 | 4% |
| Merchant copilot / analytics / insights | 18 | 4% |
| Underwriting / onboarding / KYC / compliance | 17 | 4% |
| Payout / payroll / RazorpayX | 1 | 0% |

### Rare concepts (n=397 unless noted) `[MEASURED]`

| Concept | Count |
|---|---:|
| Any mention of held-out / baseline / ablation / precision / recall | 12 |
| MCP | 5 |
| Open track / non-payments domain | 4 |
| ACP / AP2 / UAP / x402 / TAP named (n=740) | 13 |
| Prompt injection / adversarial (n=740) | 6 |
| Real or public dataset referenced | 1 |
| Dark patterns (n=740) | **0** |
| Tone / content-safety review of generated text (n=740) | **0** |

### Field-composition observations

- Roughly **45%** of the visible field sits in clusters that map onto agents Razorpay already ships in Agent Studio (recovery, dispute, cashflow, cart conversion). `[INFERENCE]`
- **~2%** of the field mentions any form of external evaluation. `[MEASURED]`
- Counting literal "Track 0X" strings gives a **misleading** picture — most repos never state a track. Counting by theme reverses the apparent ordering. `[MEASURED]`

### Methodological warning

A single-query, exact-keyword search **massively understates** conceptual competition. A search that returned "0 of 300 mention *intent*" corresponded to **112 of 565** repos in that concept space once synonyms (mandate, authorization, permission, consent, delegation, guardrail, policy) were included. Never treat keyword absence as conceptual absence.

---

## 9. Prior art worth knowing (general, ecosystem-level)

| Area | Key items |
|---|---|
| Agent security / prompt injection | **CaMeL** (Google DeepMind, 2025) — "Defeating Prompt Injections by Design"; capability metadata + custom interpreter enforcing policy so untrusted data cannot influence control flow; open-sourced at `google-research/camel-prompt-injection`; evaluated on **AgentDojo** |
| Agent security benchmarks | **AgentDojo** (includes banking suite), **DarkBench** (ICLR 2025 — dark patterns in LLM conversations, 660 prompts × 14 model families, 27k+ scored conversations), **SusBench**, **DECEPTICON** (agents as victims of dark patterns) |
| Dark pattern detection | **Dark Surfer**; ACM UIST 2023 automated detection in mobile apps; noted coverage gap — only ~45.5% of dark-pattern types covered by existing tools |
| Authorization | RFC 9396 (Rich Authorization Requests), macaroons / biscuit (attenuated delegation by caveat), object-capability security, OPA/Rego, AWS Cedar |
| Testing | Property-based testing (QuickCheck, Hypothesis), delta debugging, deterministic simulation testing (FoundationDB, TigerBeetle, Antithesis), Jepsen, concurrency schedule exploration (CHESS, Lincheck) |
| Webhook tooling | Hookdeck, Hooklistener, HookCap — commercial replay features explicitly for testing idempotency; "deliver the same signed fixture twice / replay in reverse order / deliver concurrently to two workers" is published QA practice |

---

## 10. Open unknowns worth resolving

1. **Does the application form have a second page** collecting a repo/video link? Resolvable in a browser in five minutes.
2. **Where is the build actually submitted?** Not stated anywhere.
3. **Is 5 September the intake deadline or the build deadline?** Secondary sources say intake.
4. **Who reviews, and do tracks route to different reviewers?** No roster published.
5. **How many offers exist?** Determines whether this is top-N ranking or threshold-clearing.
6. **Are the four judging criteria on the official page?** Two fetches did not surface them.
7. **Do prior editions exist?** No evidence found — appears to be a first edition, so there is no historical winner data.
8. **Is there any Reserve Pay / agentic-payment surface in test mode?** The public MCP server supports mandate orders; a Reserve Pay sandbox is undocumented publicly.

---

## 11. Sources

**Primary**
- https://razorpay.com/buildathon/
- https://forms.gle/d9r2gvxp8cmoZhon9
- https://razorpay.com/agent-studio/
- https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/
- https://razorpay.com/blog/agent-studio-ai-agents-by-razorpay/
- https://razorpay.com/blog/agentic-payments-and-npci/
- https://razorpay.com/newsroom/ (agentic payments; Agent Studio launch)
- https://razorpay.com/docs/webhooks/ and /best-practices/, /validate-test/, /faqs/
- https://razorpay.com/docs/developer-tools/mcp-server/ · https://razorpay.com/docs/mcp-server/faqs/
- https://github.com/razorpay/ (razorpay-mcp-server, razorpay-magento, razorpay-woocommerce, razorpay-prestashop)
- https://engineering.razorpay.com/ (Bumblebee, Project Viveka, security triage) · https://dev.to/razorpaytech
- https://ap2-protocol.org/ · Google Cloud blog (AP2 announcement)
- https://www.rfc-editor.org/info/rfc9396/
- PIB press releases on the CCPA Dark Patterns Guidelines, 2023 (PRID 1983994, 2134765, 2268302)
- https://www.npci.org.in/what-we-do/upi/upi-ecosystem-statistics
- GitHub Search API (repositories, issues, code)

**Secondary / reporting**
- Medianama (Agent Studio criticism; CPO response; Razorpay–Sarvam)
- Fintech Singapore, The Tribune, The Paypers, BW Disrupt, Entrackr (Agent Studio; NPCI agentic payments)
- Finextra, Digital Commerce 360 (Visa), Palo Alto Unit 42, Signifyd (agentic commerce fraud, false declines)
- Inc42, Business Standard (NPCI UAP, UPI outage)
- Velonx, CareersInCloud, FresherJobInfo, Placement Officer, CareersTN (deadline, eligibility, criteria)
- arXiv: CaMeL (2503.18813), DECEPTICON (2512.22894), SusBench (2510.11035), dark patterns in Indian quick-commerce apps (2604.02257); DarkBench (ICLR 2025)
- India Data Portal / Dataful (NPCI BD/TD mirrors)

---

*Compiled 2–3 September 2026. Every density figure is a lower bound. Where a fact could not be confirmed on a primary source it is marked `[REPORTED]`; where it could not be established at all it is marked `[UNKNOWN]`.*
