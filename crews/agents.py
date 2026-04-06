#!/usr/bin/env python3
"""
Corp CrewAI Agent & Crew Definitions
All crews run on local Ollama models (Hermes3/GLM4/Qwen) — 100% free.

Available Crews:
  - morning_briefing: Daily ops summary, priorities, reminders
  - property_ops: Tenant screening, rent analysis, maintenance triage
  - content_writer: Listing descriptions, social posts, marketing copy
  - research: Market analysis, competitor intel, property valuations
  - lease_analyst: Lease review, renewal recommendations, risk flags
"""

import os
from crewai import Agent, Task, Crew, Process, LLM

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# --- LLM Configs (all local, all free) ---

def get_llm(model_key="hermes"):
    models = {
        "hermes": "ollama/hermes3:latest",
        "glm4": "ollama/glm4:latest",
        "qwen": "ollama/qwen2.5-coder:7b",
    }
    return LLM(model=models.get(model_key, models["hermes"]), base_url=OLLAMA_BASE)


# ============================================================
# CREW: Morning Briefing
# ============================================================

def morning_briefing_crew(context: str = "", model: str = "hermes"):
    llm = get_llm(model)

    ops_analyst = Agent(
        role="Operations Analyst",
        goal="Compile a concise morning briefing covering fleet status, pending tasks, and priorities",
        backstory="You analyze operational data and create clear, actionable morning briefings for a small business owner managing properties and an AI tech corp.",
        llm=llm, verbose=False,
    )
    scheduler = Agent(
        role="Priority Scheduler",
        goal="Organize today's tasks by urgency and importance, flag deadlines",
        backstory="You are an expert at time management and task prioritization. You consider deadlines, dependencies, and business impact to create optimal daily schedules.",
        llm=llm, verbose=False,
    )
    life_coach = Agent(
        role="Life & Business Coach",
        goal="Provide motivational insights and strategic advice for the day",
        backstory="You are a supportive life and business coach who gives practical, grounded advice. You focus on sustainable progress, not hustle culture.",
        llm=llm, verbose=False,
    )

    t1 = Task(
        description=f"Create a morning operations briefing based on the following context:\n\n{context or 'No specific context provided — give a general briefing template.'}\n\nInclude: system status, pending items, any alerts or deadlines.",
        expected_output="A structured morning briefing with sections for Status, Alerts, and Action Items.",
        agent=ops_analyst,
    )
    t2 = Task(
        description="Based on the operations briefing, create a prioritized task list for today. Rank by urgency (deadlines) and importance (business impact). Include time estimates.",
        expected_output="A numbered priority list with time estimates and reasoning.",
        agent=scheduler,
    )
    t3 = Task(
        description="Review the briefing and task list. Add a brief motivational note, any strategic observations, and flag anything that could be delegated or automated.",
        expected_output="A short coaching section with strategic advice and delegation suggestions.",
        agent=life_coach,
    )

    return Crew(agents=[ops_analyst, scheduler, life_coach], tasks=[t1, t2, t3],
                process=Process.sequential, verbose=False)


# ============================================================
# CREW: Property Operations
# ============================================================

def property_ops_crew(task_type: str, details: str, model: str = "hermes"):
    llm = get_llm(model)

    screening_agent = Agent(
        role="Tenant Screening Specialist",
        goal="Evaluate tenant applications and provide screening recommendations",
        backstory="You are an experienced property manager who evaluates tenant applications based on income, rental history, references, and red flags. You balance thorough screening with fair housing compliance.",
        llm=llm, verbose=False,
    )
    financial_agent = Agent(
        role="Property Financial Analyst",
        goal="Analyze rent pricing, expenses, ROI, and financial performance",
        backstory="You specialize in residential real estate financial analysis. You compare market rents, calculate cap rates, analyze expense ratios, and recommend pricing strategies.",
        llm=llm, verbose=False,
    )
    maintenance_agent = Agent(
        role="Maintenance Triage Specialist",
        goal="Prioritize maintenance requests and create repair action plans",
        backstory="You are a property maintenance expert who triages repair requests by urgency, safety impact, cost, and tenant satisfaction. You create clear action plans with vendor recommendations.",
        llm=llm, verbose=False,
    )

    agents_map = {
        "screening": screening_agent,
        "financial": financial_agent,
        "maintenance": maintenance_agent,
    }

    prompts = {
        "screening": f"Evaluate this tenant application and provide a recommendation:\n\n{details}\n\nProvide: Score (1-10), Recommendation (approve/conditional/deny), Key Factors, Red Flags, Suggested Conditions.",
        "financial": f"Analyze this financial situation and provide recommendations:\n\n{details}\n\nProvide: Market Comparison, Recommended Action, Financial Impact, Risk Assessment.",
        "maintenance": f"Triage these maintenance requests and create an action plan:\n\n{details}\n\nProvide: Priority Ranking, Estimated Costs, Recommended Timeline, Vendor Needs, Tenant Communication Plan.",
    }

    agent = agents_map.get(task_type, maintenance_agent)
    prompt = prompts.get(task_type, prompts["maintenance"])

    task = Task(description=prompt, expected_output="A detailed analysis with clear recommendations.", agent=agent)

    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


# ============================================================
# CREW: Content Writer
# ============================================================

def content_writer_crew(content_type: str, details: str, model: str = "hermes"):
    llm = get_llm(model)

    copywriter = Agent(
        role="Property Copywriter",
        goal="Write compelling property listings and marketing copy",
        backstory="You write persuasive property listings that highlight key features, neighborhood benefits, and lifestyle appeal. You know what renters and buyers look for.",
        llm=llm, verbose=False,
    )
    social_media = Agent(
        role="Social Media Manager",
        goal="Create engaging social media content for property and business promotion",
        backstory="You create scroll-stopping social media posts for property management and tech businesses. You know platform best practices for engagement.",
        llm=llm, verbose=False,
    )
    editor = Agent(
        role="Content Editor",
        goal="Review and polish all content for clarity, accuracy, and impact",
        backstory="You are a sharp editor who catches errors, improves flow, and ensures content is professional and on-brand. You cut fluff and sharpen messaging.",
        llm=llm, verbose=False,
    )

    if content_type == "listing":
        t1 = Task(
            description=f"Write a compelling property listing based on:\n\n{details}\n\nInclude: headline, description, key features, neighborhood highlights, call-to-action.",
            expected_output="A complete property listing ready to post.",
            agent=copywriter,
        )
    elif content_type == "social":
        t1 = Task(
            description=f"Create social media posts for:\n\n{details}\n\nCreate versions for: Instagram (with hashtags), Facebook, and X/Twitter. Each should be platform-appropriate.",
            expected_output="Three platform-specific social media posts.",
            agent=social_media,
        )
    else:
        t1 = Task(
            description=f"Write marketing copy for:\n\n{details}",
            expected_output="Professional marketing copy ready to use.",
            agent=copywriter,
        )

    t2 = Task(
        description="Review and polish the content above. Fix any errors, improve clarity, ensure professional tone, and add any missing elements.",
        expected_output="Final polished version of the content.",
        agent=editor,
    )

    return Crew(agents=[copywriter, social_media, editor], tasks=[t1, t2],
                process=Process.sequential, verbose=False)


# ============================================================
# CREW: Research
# ============================================================

def research_crew(research_type: str, query: str, model: str = "hermes"):
    llm = get_llm(model)

    researcher = Agent(
        role="Market Research Analyst",
        goal="Conduct thorough market research and competitive analysis",
        backstory="You are a meticulous research analyst who synthesizes data into actionable insights. You focus on real estate markets, tech trends, and business intelligence.",
        llm=llm, verbose=False,
    )
    strategist = Agent(
        role="Business Strategist",
        goal="Turn research findings into strategic recommendations",
        backstory="You translate research into clear business strategy. You identify opportunities, risks, and competitive advantages with practical next steps.",
        llm=llm, verbose=False,
    )

    t1 = Task(
        description=f"Research the following:\n\n{query}\n\nType: {research_type}\n\nProvide comprehensive findings with data points, trends, and key observations.",
        expected_output="A structured research report with findings and data.",
        agent=researcher,
    )
    t2 = Task(
        description="Based on the research findings, provide strategic recommendations. Include: opportunities, risks, recommended actions, and timeline.",
        expected_output="Strategic recommendations with actionable next steps.",
        agent=strategist,
    )

    return Crew(agents=[researcher, strategist], tasks=[t1, t2],
                process=Process.sequential, verbose=False)


# ============================================================
# CREW: Lease Analyst
# ============================================================

def lease_analyst_crew(details: str, model: str = "hermes"):
    llm = get_llm(model)

    legal_reviewer = Agent(
        role="Lease Legal Reviewer",
        goal="Review lease terms for legal compliance and risk factors",
        backstory="You review residential leases for legal issues, missing clauses, tenant/landlord protections, and compliance with local regulations. You flag anything concerning.",
        llm=llm, verbose=False,
    )
    renewal_advisor = Agent(
        role="Lease Renewal Advisor",
        goal="Analyze lease renewals and recommend terms",
        backstory="You advise on lease renewals by analyzing market conditions, tenant history, and financial impact. You balance retention with revenue optimization.",
        llm=llm, verbose=False,
    )

    t1 = Task(
        description=f"Review this lease information and provide analysis:\n\n{details}\n\nCheck for: missing protections, risk clauses, compliance issues, recommended changes.",
        expected_output="A lease review with risk flags and recommended changes.",
        agent=legal_reviewer,
    )
    t2 = Task(
        description="Based on the lease review, provide renewal/negotiation recommendations. Consider market rates, tenant value, and business goals.",
        expected_output="Renewal recommendations with suggested terms and pricing.",
        agent=renewal_advisor,
    )

    return Crew(agents=[legal_reviewer, renewal_advisor], tasks=[t1, t2],
                process=Process.sequential, verbose=False)


# ============================================================
# Runner
# ============================================================

CREW_REGISTRY = {
    "morning_briefing": {
        "name": "Morning Briefing",
        "description": "Daily ops summary, priorities, and coaching",
        "fields": [{"name": "context", "label": "Context (fleet status, pending items, etc.)", "type": "textarea"}],
        "builder": lambda data, model: morning_briefing_crew(data.get("context", ""), model),
    },
    "property_ops": {
        "name": "Property Operations",
        "description": "Tenant screening, rent analysis, maintenance triage",
        "fields": [
            {"name": "task_type", "label": "Task Type", "type": "select", "options": ["screening", "financial", "maintenance"]},
            {"name": "details", "label": "Details", "type": "textarea"},
        ],
        "builder": lambda data, model: property_ops_crew(data.get("task_type", "maintenance"), data.get("details", ""), model),
    },
    "content_writer": {
        "name": "Content Writer",
        "description": "Listings, social media, marketing copy",
        "fields": [
            {"name": "content_type", "label": "Content Type", "type": "select", "options": ["listing", "social", "marketing"]},
            {"name": "details", "label": "Details / Brief", "type": "textarea"},
        ],
        "builder": lambda data, model: content_writer_crew(data.get("content_type", "listing"), data.get("details", ""), model),
    },
    "research": {
        "name": "Research",
        "description": "Market analysis, competitor intel, valuations",
        "fields": [
            {"name": "research_type", "label": "Research Type", "type": "select", "options": ["market", "competitor", "valuation", "technology", "general"]},
            {"name": "query", "label": "Research Question", "type": "textarea"},
        ],
        "builder": lambda data, model: research_crew(data.get("research_type", "general"), data.get("query", ""), model),
    },
    "lease_analyst": {
        "name": "Lease Analyst",
        "description": "Lease review, renewal recommendations, risk flags",
        "fields": [{"name": "details", "label": "Lease Details / Terms", "type": "textarea"}],
        "builder": lambda data, model: lease_analyst_crew(data.get("details", ""), model),
    },
}


def run_crew(crew_key: str, data: dict, model: str = "hermes") -> str:
    """Build and run a crew, return the final result as string."""
    entry = CREW_REGISTRY.get(crew_key)
    if not entry:
        return f"Unknown crew: {crew_key}"
    crew = entry["builder"](data, model)
    result = crew.kickoff()
    return str(result)
