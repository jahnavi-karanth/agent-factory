# Business Requirements Document

## Production Incident Investigation Platform

**Document Status:** Draft  
**Version:** 1.0  
**Business Owner:** Engineering Operations  
**Prepared For:** Product & Engineering  
**Priority:** Critical

---

## 1. Executive Summary

The company's engineering organization operates a number of software services that support internal and customer-facing applications.

When production incidents occur, engineers typically investigate several sources of information, including application logs, monitoring data, deployment history, service dependencies, and recent changes.

Incident investigation can take considerable time, particularly when the cause is not immediately obvious or when multiple systems may be involved.

The company wants to introduce a platform that assists engineering teams during incident investigation by organizing available evidence, identifying possible causes, and helping engineers evaluate different explanations.

The platform is intended to support engineers during investigations rather than replace engineering judgment.

---

## 2. Business Objectives

The platform should:

1. Reduce the time required to investigate production incidents.
2. Help engineers gather relevant evidence more efficiently.
3. Provide a structured view of information associated with an incident.
4. Help engineers identify possible causes.
5. Make supporting evidence for proposed causes visible.
6. Help engineers compare competing explanations.
7. Preserve an investigation history.
8. Improve consistency in incident investigation.
9. Assist teams in producing useful incident summaries.

---

## 3. Scope

The initial release will support investigation of software incidents.

The platform will support:

- Incident creation.
- Incident information collection.
- Evidence analysis.
- Investigation of relevant systems.
- Identification of possible causes.
- Comparison of possible causes.
- Additional evidence collection.
- Engineer review.
- Investigation reports.
- Investigation history.

The initial release will not automatically modify production systems.

---

## 4. Stakeholders

### Software Engineers

Use the platform to investigate incidents and understand possible causes.

### Incident Managers

Coordinate incident investigations and monitor progress.

### Engineering Managers

Review incident outcomes and identify recurring operational problems.

### Platform / Infrastructure Teams

Provide information about infrastructure and service dependencies.

### Engineering Leadership

Uses incident information to identify opportunities to improve reliability.

---

## 5. Current Process

When an incident occurs, an engineer or incident manager typically begins by examining the symptoms reported by monitoring systems or users.

The investigation may involve:

- Reviewing application logs.
- Checking recent deployments.
- Looking at service behavior.
- Examining database-related errors.
- Reviewing infrastructure information.
- Comparing current behavior with previous incidents.

Different engineers may investigate different areas simultaneously.

The findings are then discussed to determine the most likely explanation.

The current process varies depending on the incident and the engineers involved.

---

## 6. Proposed Business Process

An engineer should be able to create an investigation by providing information about an incident.

The platform should organize the available evidence and assist with investigation.

It should be possible to investigate different aspects of an incident and compare findings.

Where the available evidence does not provide enough information, the platform should identify what additional information may be useful.

Engineers should remain able to review findings, provide additional information, and reject conclusions that they believe are incorrect.

Once an investigation is complete, the platform should provide a structured summary of the investigation.

---

## 7. Functional Requirements

### 7.1 Incident Creation

Users should be able to create an incident containing information such as:

- Incident title
- Description
- Severity
- Affected service
- Approximate start time
- Current impact
- Known symptoms

---

### 7.2 Evidence Collection

Users should be able to provide information relevant to an investigation.

The platform should support evidence such as:

- Application logs
- Error messages
- Deployment information
- Monitoring information
- Service information
- Incident notes

---

### 7.3 Evidence Organization

The system should organize information associated with an incident so that investigators can distinguish between different sources and pieces of evidence.

Evidence should remain traceable to its original source.

---

### 7.4 Investigation

The platform should assist users in examining the incident and identifying information that may help determine its cause.

Different areas of a software system may need to be considered depending on the incident.

The investigation should be able to adapt when new evidence becomes available.

---

### 7.5 Possible Causes

The system should be able to present possible explanations for an incident.

For each proposed explanation, the platform should provide supporting information where available.

The system should distinguish between evidence supporting an explanation and evidence that may contradict it.

---

### 7.6 Comparison

When multiple possible explanations exist, users should be able to understand how they compare.

The platform should make relevant supporting and conflicting information visible.

---

### 7.7 Additional Investigation

When the available information is insufficient, the system should identify additional information that may help progress the investigation.

Users should be able to provide additional evidence during an ongoing investigation.

---

### 7.8 Investigation Actions

The platform should support access to relevant investigation information through configured system integrations.

Actions that could affect external systems should not be performed without appropriate authorization.

---

### 7.9 Human Review

Engineers should be able to:

- Review investigation findings.
- Provide additional information.
- Reject proposed explanations.
- Add comments.
- Confirm the outcome of an investigation.

---

### 7.10 Investigation Report

At the conclusion of an investigation, the platform should generate a structured report containing information such as:

- Incident summary
- Impact
- Timeline
- Relevant evidence
- Investigated areas
- Possible causes considered
- Evidence supporting the final conclusion
- Evidence that ruled out alternatives
- Recommended next steps

---

### 7.11 History

The platform should maintain an investigation history including significant investigation actions and findings.

---

## 8. Business Rules

The platform should not make production changes as part of the initial investigation workflow.

Investigation findings should be distinguishable from confirmed facts.

Evidence used to support an important conclusion should remain traceable.

Engineers remain responsible for confirming the final incident outcome.

Access to incident information should follow appropriate organizational permissions.

---

## 9. Non-Functional Requirements

### Security

Incident information may contain sensitive operational details and should only be accessible to authorized personnel.

### Reliability

An investigation should not be lost because an individual investigation step fails.

### Auditability

Investigation actions and significant decisions should be recorded.

### Scalability

The system should be capable of supporting multiple concurrent incident investigations.

### Recovery

Long-running investigations should be recoverable if the application or an individual processing step becomes unavailable.

---

## 10. Data Requirements

The system will maintain:

- Incidents
- Users
- Evidence
- Investigation steps
- Findings
- Possible causes
- Supporting evidence
- Comments
- Investigation history
- Final reports

---

## 11. Success Criteria

The project will be considered successful if:

- Engineers can initiate structured incident investigations.
- Relevant evidence can be collected and organized.
- Multiple possible explanations can be considered.
- Engineers can understand the evidence behind proposed conclusions.
- Additional investigation can be performed when information is insufficient.
- Investigation activity is traceable.
- A useful investigation report can be produced.
- The platform reduces the time engineers spend gathering and organizing investigation information.