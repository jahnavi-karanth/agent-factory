# Business Requirements Document

## Recruitment and Candidate Assessment Platform

**Document Status:** Draft  
**Version:** 1.0  
**Business Owner:** Talent Acquisition  
**Prepared For:** Product & Engineering  
**Priority:** High

---

## 1. Executive Summary

The company's recruitment team receives a large number of applications for technical and non-technical positions.

Recruiters currently review resumes and compare candidate experience against job requirements manually. As application volumes increase, this process requires significant time and can make it difficult for recruiters to consistently identify the most relevant candidates.

The company wants to introduce a recruitment platform that assists recruiters in reviewing candidate information and identifying candidates whose experience is relevant to a particular position.

The platform should provide recruiters with useful explanations rather than relying solely on a single automated score.

Final recruitment decisions will remain with the company's recruitment and hiring teams.

---

## 2. Business Objectives

The platform should:

1. Reduce the amount of manual effort required to review applications.
2. Make candidate information easier to compare.
3. Identify experience and skills relevant to a particular role.
4. Help recruiters identify candidates who may warrant further consideration.
5. Provide explanations for candidate assessments.
6. Allow recruiters to review and modify system-generated assessments.
7. Improve consistency in the initial screening process.

---

## 3. Scope

The initial release will support:

- Job creation.
- Job requirement management.
- Resume submission.
- Candidate information extraction.
- Candidate-to-job comparison.
- Candidate summaries.
- Recruiter review.
- Candidate search.
- Screening history.

The platform will assist recruiters but will not make final hiring decisions.

---

## 4. Stakeholders

### Recruiters

Use the platform to review applications and identify candidates for further consideration.

### Hiring Managers

Review candidates recommended for further evaluation.

### Talent Acquisition Leadership

Monitors recruitment processes and outcomes.

### Candidates

Provide resumes and application information.

### System Administrators

Manage users and system configuration.

---

## 5. Current Process

Recruiters generally receive resumes through multiple sources.

For each position, recruiters review resumes and compare candidate experience with the role requirements.

This may involve looking for:

- Relevant technical skills.
- Professional experience.
- Education.
- Certifications.
- Previous projects.
- Industry experience.

The process becomes increasingly time-consuming when a position receives a large number of applications.

---

## 6. Proposed Business Process

A recruiter should be able to create a job opening and specify the requirements for the position.

Candidate resumes should be uploaded to the platform.

The platform should organize relevant candidate information and compare it with the requirements of the position.

Recruiters should receive a summary that helps them understand the candidate's relevance to the position.

Recruiters should be able to review the assessment and make their own decision about whether the candidate should proceed.

---

## 7. Functional Requirements

### 7.1 Job Management

Recruiters should be able to create job openings containing information such as:

- Job title
- Job description
- Required skills
- Preferred skills
- Experience expectations
- Education requirements
- Location
- Employment type

---

### 7.2 Resume Upload

Recruiters should be able to upload candidate resumes in commonly used document formats.

The system should associate each resume with the appropriate job opening.

---

### 7.3 Candidate Information Extraction

The system should identify relevant information from resumes, including where available:

- Skills
- Employment history
- Education
- Certifications
- Projects
- Years of experience

The extracted information should be available for recruiter review.

---

### 7.4 Candidate Assessment

The platform should compare candidate information with the requirements associated with a job.

The assessment should identify areas where the candidate appears to meet requirements and areas where relevant information may be missing.

---

### 7.5 Candidate Summary

The platform should provide recruiters with a concise summary of each candidate.

The summary should help the recruiter understand why the candidate may or may not be relevant to the position.

---

### 7.6 Assessment Explanation

Recruiters should be able to understand the information used to produce an assessment.

Where appropriate, the platform should identify the relevant candidate information supporting the assessment.

---

### 7.7 Candidate Review

Recruiters should be able to:

- Review the candidate.
- Add notes.
- Change the screening outcome.
- Mark a candidate for further consideration.
- Remove a candidate from consideration.

---

### 7.8 Candidate Search

Recruiters should be able to search candidates using relevant information such as:

- Skills
- Experience
- Education
- Job opening
- Screening status

---

### 7.9 Bulk Processing

Recruiters should be able to submit multiple candidate resumes associated with the same job opening.

The platform should provide a practical way of reviewing the resulting candidate assessments.

---

### 7.10 Hiring Manager Review

Candidates selected by recruiters should be available for review by the relevant hiring manager.

Hiring managers should be able to provide feedback.

---

### 7.11 History

The platform should maintain the history of candidate assessments and recruiter decisions.

Changes made by recruiters should be distinguishable from system-generated assessments.

---

## 8. Business Rules

Recruiters and hiring managers retain responsibility for hiring decisions.

A system-generated assessment should not automatically result in a candidate being hired or rejected.

Candidate information should only be accessible to authorized recruitment personnel.

Candidate information should be associated with the appropriate job opening and recruitment process.

---

## 9. Non-Functional Requirements

### Security

Candidate information is confidential and should be protected from unauthorized access.

### Privacy

The system should handle candidate information responsibly and support organizational data-retention requirements.

### Performance

The platform should remain responsive when recruiters are reviewing candidates.

### Scalability

The platform should support positions receiving large numbers of applications.

### Auditability

Candidate assessment and recruiter actions should be traceable.

---

## 10. Data Requirements

The system will maintain:

- Job openings
- Job requirements
- Candidates
- Resumes
- Extracted candidate information
- Candidate assessments
- Recruiter notes
- Hiring manager feedback
- Screening decisions
- Activity history

---

## 11. Success Criteria

The project will be considered successful if:

- Recruiters can create and manage job openings.
- Candidate resumes can be processed efficiently.
- Relevant candidate information can be extracted.
- Candidate experience can be compared with job requirements.
- Recruiters receive understandable candidate assessments.
- Recruiters can review and override assessments.
- Hiring managers can review shortlisted candidates.
- Candidate information and decisions remain traceable.
- The platform reduces the time required for initial resume screening.