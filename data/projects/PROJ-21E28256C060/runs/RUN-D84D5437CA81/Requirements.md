# Corporate Expense Management Platform

BRD ID: BRD-B066A0FB9899

## Goals

- Replace the current spreadsheet- and email-based expense submission process.
- Reduce the amount of manual data entry required from employees.
- Improve the quality and completeness of expense submissions.
- Provide managers with a consistent process for reviewing expenses.
- Improve visibility into pending and completed expenses.
- Help the finance team identify expenses that require additional review.
- Provide management with useful information about company spending.
- Maintain an appropriate record of expense-related activity.

## Personas

- Employees
- Managers
- Finance Team
- Finance Leadership
- System Administrators
- Employees
- Managers
- Finance Team
- System Administrators

## Functional Requirements

- **REQ-001**: The platform shall allow authorized employees, managers, finance users, and administrators to access functionality appropriate to their responsibilities. | Revision feedback: Needs sub-200ms latency requirement.
- **REQ-002**: Users should not be able to access expense information that they are not authorized to view.
- **REQ-003**: Employees shall be able to create an expense submission.
- **REQ-004**: An expense should contain information such as Expense date, Amount, Currency, Merchant or vendor, Expense category, Business purpose, Description, and Supporting documentation where applicable. | Clarification decision (Q-001): idk
- **REQ-005**: The system should identify information that is required before an expense can be submitted. | Clarification decision (Q-001): idk
- **REQ-006**: Employees should be able to provide receipts or other supporting documents associated with an expense.
- **REQ-007**: The platform should make it possible to extract relevant information from submitted receipts where the information can be reliably identified. | Clarification decision (Q-002): idk
- **REQ-008**: Employees must be able to review and correct information extracted from a receipt before submitting the expense. | Clarification decision (Q-002): idk
- **REQ-009**: The platform should assist employees in assigning an appropriate category to an expense.
- **REQ-010**: The employee should be able to change the suggested category when necessary.
- **REQ-011**: The system should maintain consistent categories so that expenses can subsequently be reported and analyzed.
- **REQ-012**: An employee should be able to submit a completed expense for review.
- **REQ-013**: The system should prevent incomplete submissions where required information is missing. | Clarification decision (Q-001): idk
- **REQ-014**: Once submitted, the expense should have a status that allows the employee and relevant reviewers to understand its current stage.
- **REQ-015**: Managers should be able to view expenses requiring their attention.
- **REQ-016**: A manager should be able to review expense information, review supporting documentation, approve an expense, reject or return an expense, and provide comments when additional information is required.
- **REQ-017**: The employee should be informed when action has been taken on an expense.
- **REQ-018**: The finance team should be able to access expenses that require finance review.
- **REQ-019**: Finance users should be able to examine expense details and supporting documentation and take appropriate action according to company policy.
- **REQ-020**: The system should make it possible to distinguish between expenses that have completed approval and those that still require action.
- **REQ-021**: The platform should provide employees and authorized reviewers with the current status of an expense.
- **REQ-022**: The status should make it clear whether an expense is Being prepared, Submitted, Awaiting review, Returned for additional information, Approved, Rejected, or Completed.
- **REQ-023**: The exact lifecycle should be consistent across the application.
- **REQ-024**: Relevant users should receive notifications when an action is required or when an important change occurs to an expense.
- **REQ-025**: Authorized users should be able to locate expenses using relevant information.
- **REQ-026**: The finance team should be able to search and filter expenses based on information such as Employee, Department, Expense category, Date, Status, and Amount.
- **REQ-027**: The platform should provide finance users with information that helps them understand company expense activity.
- **REQ-028**: Reports should support analysis by dimensions such as Time period, Department, Employee, Expense category, and Approval status.
- **REQ-029**: The finance team should be able to use the resulting information for regular financial review.
- **REQ-030**: The platform should assist the finance team in identifying expenses that appear inconsistent with expected company spending behavior or expense policies.
- **REQ-031**: The system should maintain a history of significant actions performed on an expense.

## Non-Functional Requirements

- Expense information and supporting documents should only be accessible to authorized users.
- The system should protect sensitive employee and financial information.
- Submitted expenses should not be lost if an individual processing step fails.
- The system should provide appropriate handling for failures during receipt processing or other automated operations.
- Normal user operations such as viewing an expense, submitting an expense, or retrieving an expense list should provide a responsive user experience.
- The platform should be capable of supporting the organization's expected growth in employees and expense submissions without requiring a fundamental redesign.
- Important expense lifecycle events and user actions should be traceable.

## Constraints

- Not specified

## Human Clarifications & Decisions

- **Q**: Which specific expense attributes from REQ-004 are mandatory for a successful expense submission?
  **A**: idk
- **Q**: What constitutes reliable identification for information extracted from submitted receipts?
  **A**: idk

## Out-of-Scope

- Not specified

## Open Questions

- The platform will initially be used internally by the organization.
- Employees and managers will have authenticated access to the system.
- Company expense policies will continue to be maintained by the finance organization.
- The platform will assist with expense processing but will not replace financial policies or the responsibilities of finance personnel.
- Employees can submit expenses through a centralized platform.
- Receipt information can be captured with reduced manual entry.
- Managers can review and process expenses through the platform.
- Employees can track the progress of their submissions.
- Finance users can identify and investigate expenses requiring attention.
- Management can obtain useful expense information through reporting.
- Expense actions can be traced through an audit history.
- The organization experiences a reduction in manual expense-processing effort.
