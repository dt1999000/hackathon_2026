from app.models import CompanyProfileBase


def _eur(value: float | None) -> str | None:
    if value is None:
        return None
    return f"€{value:,.0f}"


def _bullets(label: str, values: list[str]) -> str | None:
    if not values:
        return None
    items = "\n".join(f"- {v}" for v in values)
    return f"{label}:\n{items}"


def render_company_profile_text(profile: CompanyProfileBase) -> str:
    """Render a CompanyProfile's fields as an Appendix-A-style text
    description. This is the text that gets embedded for later
    cosine-similarity retrieval — every structured field that's set feeds
    into it, so the embedding reflects the same information a human would
    read off the profile.
    """
    sections: list[str] = []

    header_lines = [f"Company: {profile.company_name}"]
    if profile.base_location:
        header_lines.append(f"Location: {profile.base_location}")
    if profile.founded_year:
        header_lines.append(f"Founded: {profile.founded_year}")
    if profile.employee_count:
        header_lines.append(f"Employees: {profile.employee_count}")
    if profile.annual_revenue_eur:
        header_lines.append(f"Annual revenue: {_eur(profile.annual_revenue_eur)}")
    sections.append("\n".join(header_lines))

    does = _bullets("Does", profile.capabilities)
    if does:
        sections.append(does)

    cannot = _bullets("Cannot show / explicit exclusions", profile.explicit_exclusions)
    if cannot:
        sections.append(cannot)

    certs = _bullets("Certifications", profile.certifications)
    if certs:
        sections.append(certs)

    where_lines = []
    if profile.served_regions:
        where_lines.append(f"Operates in: {', '.join(profile.served_regions)}")
    if profile.max_radius_km:
        where_lines.append(f"Up to {profile.max_radius_km} km from {profile.base_location or 'base'}")
    if profile.excluded_regions:
        where_lines.append(f"Excluded regions: {', '.join(profile.excluded_regions)}")
    if where_lines:
        sections.append("Where:\n" + "\n".join(where_lines))

    contract_lines = []
    if profile.min_contract_value_eur or profile.max_contract_value_eur:
        lo = _eur(profile.min_contract_value_eur) or "?"
        hi = _eur(profile.max_contract_value_eur) or "?"
        contract_lines.append(f"Contract size: {lo}–{hi}")
    if profile.partner_threshold_eur:
        contract_lines.append(
            f"Needs a partner above {_eur(profile.partner_threshold_eur)}"
        )
    if profile.contractor_role:
        contract_lines.append(f"Contractor role: {profile.contractor_role}")
    if profile.max_self_perform_pct is not None:
        contract_lines.append(
            f"Max self-performed share: {profile.max_self_perform_pct}%"
        )
    if contract_lines:
        sections.append("Contract size:\n" + "\n".join(contract_lines))

    finance_lines = []
    if profile.guarantee_limit_total_eur:
        finance_lines.append(
            f"Guarantee limit: {_eur(profile.guarantee_limit_total_eur)} total"
        )
    if profile.guarantee_currently_committed_eur:
        finance_lines.append(
            f"Currently committed: {_eur(profile.guarantee_currently_committed_eur)}"
        )
    if finance_lines:
        sections.append("Financial limit:\n" + "\n".join(finance_lines))

    availability_lines = []
    if profile.available_from:
        availability_lines.append(f"Free from: {profile.available_from}")
    if profile.capacity_note:
        availability_lines.append(profile.capacity_note)
    if availability_lines:
        sections.append("Availability:\n" + "\n".join(availability_lines))

    refs = _bullets("Can show / reference projects", profile.reference_projects)
    if refs:
        sections.append(refs)

    hardliners = _bullets(
        "Hard constraints (must not be violated)", profile.custom_hardliners
    )
    if hardliners:
        sections.append(hardliners)

    if profile.self_description:
        sections.append(f'In their own words: "{profile.self_description}"')

    return "\n\n".join(sections)
