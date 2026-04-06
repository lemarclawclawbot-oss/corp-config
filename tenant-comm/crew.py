#!/usr/bin/env python3
"""
Tenant Communication Crew — AI agents for property management communications.
Uses CrewAI + local Hermes3 (via Ollama) for drafting, reviewing, and managing
tenant messages: complaints, maintenance, lease reminders, and general comms.
"""

import os
from crewai import Agent, Task, Crew, Process, LLM

# Local Hermes3 via Ollama for all tenant comms
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

hermes_llm = LLM(
    model="ollama/hermes3:latest",
    base_url=OLLAMA_BASE,
)

# --- Agents ---

comm_drafter = Agent(
    role="Tenant Communication Specialist",
    goal="Draft clear, professional, and empathetic communications to tenants",
    backstory=(
        "You are an experienced property management communications specialist. "
        "You write messages that are warm yet professional, legally careful, "
        "and always respectful of tenant rights. You know landlord-tenant law basics "
        "and always maintain a constructive tone."
    ),
    llm=hermes_llm,
    verbose=False,
)

complaint_handler = Agent(
    role="Complaint Resolution Specialist",
    goal="Analyze tenant complaints and draft appropriate responses with action plans",
    backstory=(
        "You specialize in de-escalating tenant complaints and turning them into "
        "actionable resolution plans. You acknowledge concerns, propose timelines, "
        "and ensure the tenant feels heard while protecting the landlord's interests."
    ),
    llm=hermes_llm,
    verbose=False,
)

lease_manager = Agent(
    role="Lease & Notice Coordinator",
    goal="Generate lease-related notices, reminders, and formal communications",
    backstory=(
        "You handle all lease-related communications: renewal notices, rent reminders, "
        "late payment notices, move-in/move-out instructions, and lease violation notices. "
        "You ensure all communications are legally appropriate and properly formatted."
    ),
    llm=hermes_llm,
    verbose=False,
)

maintenance_coordinator = Agent(
    role="Maintenance Communication Coordinator",
    goal="Coordinate maintenance communications between tenants and service providers",
    backstory=(
        "You manage all maintenance-related communications: scheduling repairs, "
        "providing status updates, coordinating access with tenants, and following up "
        "after work is completed. You keep everyone informed and set clear expectations."
    ),
    llm=hermes_llm,
    verbose=False,
)


# --- Task Factories ---

def draft_message_task(tenant_name: str, subject: str, context: str) -> Task:
    """Draft a general tenant communication."""
    return Task(
        description=(
            f"Draft a professional message to tenant '{tenant_name}' regarding: {subject}\n\n"
            f"Context: {context}\n\n"
            "Requirements:\n"
            "- Professional but warm tone\n"
            "- Clear action items if any\n"
            "- Appropriate greeting and sign-off\n"
            "- Keep it concise but thorough"
        ),
        expected_output="A complete, ready-to-send message to the tenant.",
        agent=comm_drafter,
    )


def handle_complaint_task(tenant_name: str, complaint: str, property_info: str = "") -> Task:
    """Handle a tenant complaint with a response and action plan."""
    return Task(
        description=(
            f"Tenant '{tenant_name}' has submitted a complaint:\n\n"
            f'"{complaint}"\n\n'
            f"Property info: {property_info or 'Not specified'}\n\n"
            "Requirements:\n"
            "1. Draft an empathetic acknowledgment response to the tenant\n"
            "2. Create an internal action plan with steps and timeline\n"
            "3. Suggest follow-up schedule"
        ),
        expected_output=(
            "Two sections:\n"
            "1. TENANT RESPONSE — The message to send to the tenant\n"
            "2. ACTION PLAN — Internal steps, responsible parties, and timeline"
        ),
        agent=complaint_handler,
    )


def lease_reminder_task(tenant_name: str, reminder_type: str, details: str) -> Task:
    """Generate lease-related notices and reminders."""
    return Task(
        description=(
            f"Generate a {reminder_type} notice for tenant '{tenant_name}'.\n\n"
            f"Details: {details}\n\n"
            "Requirements:\n"
            "- Formal but respectful tone\n"
            "- Include all legally required information\n"
            "- Clear deadlines and next steps\n"
            "- Contact information for questions"
        ),
        expected_output="A complete, properly formatted notice ready to send.",
        agent=lease_manager,
    )


def maintenance_update_task(
    tenant_name: str, issue: str, status: str, details: str
) -> Task:
    """Coordinate maintenance communications."""
    return Task(
        description=(
            f"Send a maintenance update to tenant '{tenant_name}'.\n\n"
            f"Issue: {issue}\n"
            f"Status: {status}\n"
            f"Details: {details}\n\n"
            "Requirements:\n"
            "- Clear status update\n"
            "- Expected timeline\n"
            "- Any preparation needed from tenant\n"
            "- Contact for emergencies"
        ),
        expected_output="A clear maintenance update message ready to send to the tenant.",
        agent=maintenance_coordinator,
    )


# --- Crew Runner ---

def run_crew(task: Task) -> str:
    """Execute a single-task crew and return the result."""
    crew = Crew(
        agents=[task.agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff()
    return str(result)


# --- Convenience Functions ---

def draft_message(tenant_name: str, subject: str, context: str) -> str:
    task = draft_message_task(tenant_name, subject, context)
    return run_crew(task)


def handle_complaint(tenant_name: str, complaint: str, property_info: str = "") -> str:
    task = handle_complaint_task(tenant_name, complaint, property_info)
    return run_crew(task)


def lease_reminder(tenant_name: str, reminder_type: str, details: str) -> str:
    task = lease_reminder_task(tenant_name, reminder_type, details)
    return run_crew(task)


def maintenance_update(tenant_name: str, issue: str, status: str, details: str) -> str:
    task = maintenance_update_task(tenant_name, issue, status, details)
    return run_crew(task)


if __name__ == "__main__":
    # Quick test
    print("Testing Tenant Communication Crew...")
    result = draft_message(
        "John Smith",
        "Welcome to the property",
        "New tenant moving in on April 15th, 2-bedroom unit 4B"
    )
    print(f"\n--- Draft Result ---\n{result}")
