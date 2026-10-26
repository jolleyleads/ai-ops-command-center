# AutoMake AI Homepage Master Prompt

Act as a senior conversion copywriter, brand designer, accessibility specialist, and full-stack engineer. Build and publish a polished, mobile-first homepage for AutoMake AI at https://automakeai.live. Implement it in the existing jolleyleads/ai-ops-command-center Flask application deployed on Render. Deliver working code, not only a mockup. Keep the existing app available at /chat-operator and preserve its research, verification, outreach, reply, and booking workflows.

## Brand and audience

Use the existing AutoMake AI logo at /chat-operator/automake-logo.svg. Preserve its emerald green, black, and white identity. Use restrained green accents, warm off-white sections, generous spacing, confident typography, sharp hierarchy, and an approachable tone. The tagline is “Ask. Automate. Execute.” Matthew Jolley is the founder, based in Portsmouth, Virginia. The demo contact is info@automakeai.live. Do not invent credentials or certifications.

Speak directly to busy owners and small teams in home services, local businesses, and professional services. They are juggling customer work, prospecting, contact research, emails, follow-ups, and scheduling. The problem is scattered effort and missed next steps. The offer is one visible workflow that helps move opportunities toward conversations and agreed appointments.

## Main message

Lead with the business problem, not technical terminology. A strong hero direction is:

“Your next customer shouldn’t get lost in your to-do list.”

Supporting copy must explain plainly that AutoMake AI helps find businesses, collect public contacts, check mailbox status, prepare personalized outreach, manage configured follow-ups, track replies, and handle agreed appointments. Position it as assistance with the work, not a guarantee of leads, replies, revenue, or appointments.

Use “See it in a demo” as the primary call to action and “Open app” as a clear secondary path. Every demo CTA must lead to the demo section.

## Product truth

Describe only supported functionality:

1. AutoHunt discovers businesses, filters against the request, and collects public contact details with sources.
2. Mailbox verification is separate from contact discovery. Unknown, catch-all, risky, expired, or rejected results must not be presented as verified. Provider allowances and connection requirements apply.
3. Outreach drafts show the recipient, subject, body, and attachment for review. Sending starts with Send or Activate, subject to the app’s checks.
4. Configured follow-ups may run after activation. Replies, opt-outs, and workflow rules control further outreach.
5. Sent records require confirmed sending evidence. Sending does not prove inbox delivery or a reply.
6. Appointments require an agreed time and confirmed calendar availability.

Never claim unlimited free verification, guaranteed deliverability, guaranteed results, real-time calendar slots that have not been checked, or integrations that have not been implemented. Do not include internal error codes, provider setup instructions, or engineering detail in the main sales story.

## Page structure

Create a complete, coherent page rather than a collection of generic feature cards:

- A clear header with the existing logo, concise navigation, Open app, and Book a demo.
- A problem-led hero with a strong headline, short explanation, primary CTA, and an attractive HTML/CSS product workflow preview. Label the preview as illustrative so it cannot be mistaken for a live result.
- A compact audience strip.
- A section explaining the cost of manual research, disconnected outreach, and missed follow-ups, paired with how AutoMake AI helps.
- A concrete four-step workflow: Ask; Check and review; Send and follow up; Handle replies and agreed appointments.
- A credibility section grounded in inspectable product behavior: source links, clear email statuses, reviewed sending, and founder access. Use real credentials only when supplied and substantiated.
- A review area only if authentic reviews are supplied or fictional examples remain explicitly labeled. Never invent customers, verified reviews, CEO endorsements, star ratings, case studies, awards, or performance statistics. Fictional business names and illustrative quotes may be used only with an obvious disclosure immediately above the section and “Fictional sample” on every card. Replace those samples with permissioned real reviews when available.
- A prominent demo request section using info@automakeai.live.
- Practical FAQs addressing the workflow, sending approval, verification limits, and a personal demo.
- A final CTA and useful footer.

## Demo request behavior

The existing email address is receive-only forwarding to the founder’s Gmail. Do not claim it is a sending mailbox or a scheduling service.

Build an accessible form for name, business, email, optional preferred date/time, time zone, and the main business problem. Preselect the browser’s time zone while allowing correction. Validate required fields and email syntax. Make the final action “Request my demo.”

With the current email-based implementation, construct a properly URL-encoded mailto draft to info@automakeai.live containing the form information. Clearly explain before submission: “Opens a draft in your email app. Send it to request your demo; your time is confirmed by email.” Provide a visible fallback link to open the email draft and a direct contact link. Do not show “Booked,” “Request received,” or any other server-confirmation message when no message was actually received. Do not transmit form entries to analytics or third parties in the background.

If a real scheduling integration is subsequently provided, implement it using verified availability and durable booking receipts. Never display invented available slots or silently create calendar events.

## Design and accessibility

Make the page feel premium, focused, and human. Use responsive grids that become clear single-column sections on phones. Keep body copy readable, tap targets comfortable, form labels explicit, keyboard focus visible, and input text at least 16px on mobile to avoid iPhone zoom. Include a skip link, semantic landmarks, logical heading levels, alt text, sufficient contrast, reduced-motion support, and no horizontal overflow at 320px, 390px, tablet, or desktop widths. Keep the real logo visible and proportionate.

Use product-oriented visuals made from HTML/CSS instead of unrelated stock photos or fabricated screenshots. Avoid rotating carousels, fake activity counters, fake countdowns, exaggerated badges, excessive animation, clutter, technical jargon, and repetitive sections. Keep pages fast with local assets and minimal JavaScript.

## Engineering and completion

Inspect existing routes and tests before editing. Serve the homepage at /. Preserve /chat-operator, login, Gmail, API, dashboard, and workflow routes. Make no unrelated changes to sending, verification, or credential storage. Keep credentials and personal data out of source, screenshots, logs, and prompt files.

Run appropriate route, asset, and interaction checks. Verify the mailto recipient, escaping, form validation, fallback behavior, and honest request status without sending a demo email. Inspect desktop and phone layouts in the browser. Fix observed issues, run CI, merge the reviewed change, and monitor the existing Render auto-deploy until it is live. Confirm the actual custom domain serves the new homepage and the app remains reachable. Return the live URL, this reusable prompt, and a useful screenshot. Clearly state any remaining limits, including the illustrative reviews and email-based demo requests.
