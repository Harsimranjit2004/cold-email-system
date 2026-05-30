import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

YOUR_PROFILE = """
Name: Harsimranjit Singh
Role: Junior Software Developer
Skills: TypeScript, Node.js, Next.js, Python, FastAPI, AWS, Docker, Kubernetes, MongoDB, PostgreSQL, Redis
Education: Computer Programming Diploma, Seneca Polytechnic
Experience: Built AI automation systems and cloud backend infrastructure at Legion Automations
Portfolio: Synapse (self-hosted ML platform), Kubernetes-based code execution platform (15,000+ jobs/day)
Looking for: Junior/entry-level software engineering or DevOps roles in Toronto/GTA or remote Canada
Calendly: https://calendly.com/harsimranjit-softwareengineer/30min
LinkedIn: https://www.linkedin.com/in/harsimranjits1/
"""

INITIAL_TEMPLATE_REFERENCE = """
Hi Benedict,

I came across your profile while researching talent acquisition at TD and wanted to reach out directly.

I'm a Computer Programming graduate from Seneca Polytechnic with production experience building AI automation systems and cloud backend infrastructure using Node.js, TypeScript, AWS, and Docker. I'm currently targeting junior software engineering roles in the GTA and TD's engineering org is high on my list.

Given your executive recruiting background, I'd value 15 minutes of your time — around what junior engineering hiring looks like at TD right now and whether there are openings that might be a fit for my background.

Calendly (15–30 min): https://calendly.com/harsimranjit-softwareengineer/30min
LinkedIn: https://www.linkedin.com/in/harsimranjits1/

Happy to share my resume if useful. Thanks for your time, Benedict.

Harsimranjit Singh
"""

FOLLOWUP_1_REFERENCE = """
Hi [Name],

Wanted to follow up on my note from last week in case it got buried.

I've attached my resume in case it's helpful — either for your review or to forward to whoever handles junior engineering hiring on your end.

Still happy to connect for 15 minutes if the timing works.

Calendly: https://calendly.com/harsimranjit-softwareengineer/30min

Thanks again,
Harsimranjit Singh
"""


def personalize_email(
    lead_name: str,
    lead_title: str,
    lead_company: str,
    sequence_step: int = 1,
    previous_email: str = None,
) -> dict:

    if sequence_step == 1:
        prompt = f"""
You are writing a cold outreach email on behalf of a job seeker.

SENDER PROFILE:
{YOUR_PROFILE}

RECIPIENT:
- Name: {lead_name}
- Title: {lead_title}
- Company: {lead_company}

REFERENCE EMAIL (use this as a style and tone guide only — do NOT copy it):
{INITIAL_TEMPLATE_REFERENCE}

YOUR TASK:
Write a fresh, personalized cold email to {lead_name} at {lead_company}.

Think carefully about:
- What does someone with the title "{lead_title}" actually care about?
- What angle makes most sense for reaching out to them specifically?
  - Recruiter/Talent/HR → they place people, mention you're actively looking and make it easy for them
  - Engineering Manager/Tech Lead → they build teams, speak to your technical skills and what you'd contribute
  - CTO/VP Eng → they think about the org, mention your ambition and what you're building
  - Other → find the most logical connection between their role and your goal
- What specific thing about {lead_company} makes it worth mentioning?
- How do you make this feel like a real human wrote it, not a template?

RULES:
- Match the tone of the reference email: direct, confident, not desperate
- Keep body under 150 words
- End with Calendly link and LinkedIn
- Sign off as Harsimranjit Singh
- Do NOT start with "I hope this email finds you well" or any generic opener
- The opening line must be specific to {lead_name} or {lead_company}

Return ONLY in this format:
SUBJECT: <subject line>
BODY:
<email body>
"""

    elif sequence_step == 2:
        prompt = f"""
You are writing a follow-up cold email on behalf of a job seeker.

SENDER PROFILE:
{YOUR_PROFILE}

RECIPIENT:
- Name: {lead_name}
- Title: {lead_title}
- Company: {lead_company}

PREVIOUS EMAIL SENT:
{previous_email or "An initial outreach email was sent last week introducing Harsimranjit and asking for 15 minutes."}

REFERENCE FOLLOW-UP (use as style guide only — do NOT copy):
{FOLLOWUP_1_REFERENCE}

YOUR TASK:
Write a short, natural follow-up email to {lead_name}.

Think about:
- They didn't reply — maybe they were busy, maybe it got buried
- Don't be pushy or guilt-trip them
- Add a small new piece of value (mention resume, offer to forward to right person)
- Keep it under 80 words — brevity is key for follow-ups

RULES:
- Same tone: direct, warm, not desperate
- Reference the previous email briefly
- Include Calendly link
- Sign off as Harsimranjit Singh

Return ONLY in this format:
SUBJECT: <subject line — keep it as a reply thread, e.g. "Re: Quick intro">
BODY:
<email body>
"""

    else:
        prompt = f"""
You are writing a final follow-up cold email on behalf of a job seeker.

SENDER PROFILE:
{YOUR_PROFILE}

RECIPIENT:
- Name: {lead_name}
- Title: {lead_title}
- Company: {lead_company}

PREVIOUS EMAIL SENT:
{previous_email or "Two emails were sent previously with no reply."}

YOUR TASK:
Write a short, graceful final follow-up to {lead_name}.

Think about:
- This is the last email — make it count but don't burn the bridge
- A good final email either gets a reply or leaves a good impression
- Consider a slight pivot: mention something you're working on, a result you got, or simply close the loop gracefully
- Under 60 words

RULES:
- No pressure, no guilt
- Leave the door open for future
- Sign off as Harsimranjit Singh
- Include LinkedIn link

Return ONLY in this format:
SUBJECT: <subject line>
BODY:
<email body>
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )

    response = message.content[0].text.strip()

    # Parse subject and body
    lines = response.split('\n')
    subject = "Quick intro — Junior Software Engineer"
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith("SUBJECT:"):
            subject = line.replace("SUBJECT:", "").strip()
        elif line.startswith("BODY:"):
            in_body = True
        elif in_body:
            body_lines.append(line)

    body = '\n'.join(body_lines).strip()

    return {
        "subject": subject,
        "body": body if body else response
    }