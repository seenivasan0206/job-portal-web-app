/* ============================================================
   Candidate Profile Page JavaScript
   - Loads aggregated profile data
   - CRUD for all repeatable sections via generic API
   - Tag input with suggest-as-you-type for skills
   - Photo upload with preview
   - Resume upload with skill extraction
   - Completeness ring update
   ============================================================ */

window.candidateProfile = (function () {
    "use strict";

    var state = {
        sections: [
            "key-skills", "employment", "education", "it-skills",
            "internships", "projects", "languages", "online-profiles",
            "work-samples", "certifications", "publications",
            "presentations", "patents", "competitive-exams",
            "academic-achievements"
        ],
        currentEditItem: null,
        currentEditSection: null,
        skillSuggestions: [],
        skillTags: [],
        photoDataUrl: null,
    };

    function escapeHtml(str) {
        if (!str) return "";
        return String(str).replace(/[&<>"']/g, function (m) {
            var map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" };
            return map[m];
        });
    }

    function formatDate(val) {
        if (!val) return "";
        var d = new Date(val);
        if (isNaN(d.getTime())) return val;
        return d.toISOString().split("T")[0];
    }

    function showSkeleton(ids) {
        ids.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.innerHTML = '<div class="ds-skeleton ds-skeleton-line" style="width:100%;height:16px;"></div>';
        });
    }

    async function loadProfile() {
        try {
            var res = await fetch("/api/candidate/profile");
            var data = await res.json();
            if (!data.success) {
                dashboardShared.showToast("Failed to load profile", "error");
                return;
            }
            renderProfile(data);
            renderCompleteness(data.completeness || 0);
        } catch (e) {
            dashboardShared.showToast("Error loading profile: " + e.message, "error");
        }
    }

    function renderProfile(data) {
        var p = data.profile || {};

        // Headline
        var headlineEl = document.getElementById("profile-headline");
        if (headlineEl) headlineEl.value = p.headline || "";

        // Summary
        var summaryEl = document.getElementById("profile-summary-text");
        if (summaryEl) summaryEl.value = (p.profile_summary && p.profile_summary.summary) ? p.profile_summary.summary : (p.summary || "");

        // Profile photo
        var photoPreview = document.getElementById("profile-photo-preview");
        var photoPlaceholder = document.getElementById("photo-placeholder");
        if (p.profile_photo_url && photoPreview && photoPlaceholder) {
            photoPreview.src = p.profile_photo_url;
            photoPreview.style.display = "block";
            photoPlaceholder.style.display = "none";
        }

        // General resume
        var resumeDisplay = document.getElementById("resume-display");
        if (resumeDisplay) {
            if (p.general_resume_path) {
                var filename = p.general_resume_path.split('/').pop();
                resumeDisplay.innerHTML = '<a href="/candidate/resume/download" class="btn btn-primary btn-sm" style="display:inline-block;"><i class="fas fa-download"></i> Download ' + escapeHtml(filename) + '</a>';
            } else {
                resumeDisplay.innerHTML = '<p style="color: var(--color-text-secondary);">No resume uploaded yet.</p>';
            }
        }

        // Personal details
        renderSingletonDisplay("personal", data.personal_details, [
            ["date_of_birth", "DOB", formatDate],
            ["gender", "Gender"],
            ["marital_status", "Marital Status"],
            ["nationality", "Nationality"],
            ["current_location", "Location"],
            ["hometown", "Hometown"],
            ["permanent_address", "Address"],
            ["pincode", "Pincode"],
        ]);

        // Preferences
        renderSingletonDisplay("preferences", data.preferences, [
            ["current_industry", "Industry"],
            ["current_job_role", "Role"],
            ["desired_job_type", "Job Type"],
            ["desired_employment_type", "Employment"],
            ["preferred_shift", "Shift"],
            ["current_ctc", "CTC"],
            ["expected_ctc", "Expected CTC"],
            ["notice_period", "Notice Period"],
        ]);
        var locsEl = document.getElementById("preferences-display");
        if (data.preferred_locations && data.preferred_locations.length > 0) {
            var locsHtml = '<div style="margin-top:8px;"><strong>Locations:</strong> ' +
                data.preferred_locations.map(escapeHtml).join(", ") + "</div>";
            if (locsEl) locsEl.insertAdjacentHTML("beforeend", locsHtml);
        }

        // Summary singleton
        if (data.profile_summary) {
            var summaryText = data.profile_summary.summary || "";
            var sumDisplay = document.getElementById("summary-display");
            if (sumDisplay) sumDisplay.innerHTML = summaryText ? '<p style="line-height:1.6;">' + escapeHtml(summaryText) + "</p>" : '<p style="color:var(--color-text-muted);">No summary added yet.</p>';
        }

        // Repeatable sections
        state.sections.forEach(function (section) {
            var listId = section + "-list";
            var items = getItemsForSection(data, section);
            renderItems(listId, items, section);
        });

        // Key skills
        renderSkillTags(data.key_skills || []);
        updateSkillCount();
        state.skillTags = (data.key_skills || []).map(function (s) { return s.skill_name; });
    }

    function getItemsForSection(data, section) {
        var map = {
            "employment": "employment", "education": "education",
            "it-skills": "it_skills", "internships": "internships",
            "projects": "projects", "online-profiles": "online_profiles",
            "work-samples": "work_samples", "certifications": "certifications",
            "publications": "publications", "presentations": "presentations",
            "patents": "patents", "competitive-exams": "competitive_exams",
            "academic-achievements": "academic_achievements",
            "key-skills": "key_skills", "languages": "languages",
            "preferred-locations": "preferred_locations",
        };
        return data[map[section]] || [];
    }

    function renderItems(listId, items, section) {
        var el = document.getElementById(listId);
        if (!el) return;
        if (!items || items.length === 0) {
            el.innerHTML = '<div class="ds-empty"><i class="fas fa-info-circle"></i><p>No entries yet. Click "Add" to get started.</p></div>';
            return;
        }
        var html = "";
        items.forEach(function (item) {
            html += renderItemCard(item, section);
        });
        el.innerHTML = html;
    }

    function renderItemCard(item, section) {
        var title = "";
        var subtitle = "";
        var details = "";

        if (section === "employment") {
            title = item.company_name || "";
            subtitle = item.job_title || "";
            details = [item.employment_type, item.is_current ? "Current" : "", item.start_date, item.end_date].filter(Boolean).join(" · ");
        } else if (section === "education") {
            title = item.course_degree || "";
            subtitle = item.institute || "";
            details = [item.education_level, item.year_of_passing].filter(Boolean).join(" · ");
        } else if (section === "it-skills") {
            title = item.skill_name || "";
            details = [item.version, item.proficiency, item.experience_years + "y " + item.experience_months + "m"].filter(Boolean).join(" · ");
        } else if (section === "internships") {
            title = item.role_title || "";
            subtitle = item.organization_name || "";
            details = [item.start_date, item.end_date, item.stipend].filter(Boolean).join(" · ");
        } else if (section === "projects") {
            title = item.title || "";
            subtitle = item.client_name || "";
            details = [item.status, item.start_date, item.end_date].filter(Boolean).join(" · ");
        } else if (section === "online-profiles") {
            title = item.platform || "";
            subtitle = "";
            details = item.profile_url || "";
        } else if (section === "work-samples") {
            title = item.title || "";
            subtitle = "";
            details = item.url || "";
        } else if (section === "certifications") {
            title = item.name || "";
            subtitle = item.issuing_authority || "";
            details = [item.certificate_id, item.issue_date, item.expiry_date].filter(Boolean).join(" · ");
        } else if (section === "publications") {
            title = item.title || "";
            details = item.url || (item.publisher_journal + " " + item.pub_date).trim();
        } else if (section === "presentations") {
            title = item.title || "";
            details = item.present_date || "";
        } else if (section === "patents") {
            title = item.title || "";
            subtitle = item.patent_office || "";
            details = [item.patent_number, item.status, item.patent_date].filter(Boolean).join(" · ");
        } else if (section === "competitive-exams") {
            title = item.exam_name || "";
            details = [item.score_percentile, item.rank, item.year].filter(Boolean).join(" · ");
        } else if (section === "academic-achievements") {
            title = item.title || "";
            details = item.year || "";
        } else if (section === "key-skills") {
            title = item.skill_name || "";
        } else if (section === "languages") {
            title = item.language || "";
            var parts = [];
            if (item.can_read) parts.push("R");
            if (item.can_write) parts.push("W");
            if (item.can_speak) parts.push("S");
            details = parts.join("/") || "";
        }

        var actions = '<button class="ds-btn ds-btn-ghost ds-btn-sm" data-action="edit" data-section="' + section + '" data-entry-id="' + item.id + '" onclick="candidateProfile.editItem(' + item.id + ',\'' + section + '\')"><i class="fas fa-edit"></i> Edit</button>' +
            '<button class="ds-btn ds-btn-ghost ds-btn-sm" data-action="delete" data-section="' + section + '" data-entry-id="' + item.id + '" onclick="candidateProfile.deleteItem(' + item.id + ',\'' + section + '\')"><i class="fas fa-trash"></i> Delete</button>';

        return '<div class="ds-applicant-card" data-section="' + section + '" data-entry-id="' + item.id + '" style="display:flex;justify-content:space-between;align-items:center;">' +
            '<div style="flex:1;overflow:hidden;">' +
            '<div style="font-weight:600;color:var(--color-text);font-size:15px;">' + escapeHtml(title) + '</div>' +
            (subtitle ? '<div style="color:var(--color-text-muted);font-size:13px;">' + escapeHtml(subtitle) + '</div>' : "") +
            (details ? '<div style="color:var(--color-text-muted);font-size:12px;margin-top:4px;">' + escapeHtml(details) + '</div>' : "") +
            "</div>" +
            '<div style="margin-left:var(--space-2);display:flex;gap:var(--space-1);">' + actions + "</div>" +
            "</div>";
    }

    function renderSingletonDisplay(key, data, fields) {
        var el = document.getElementById(key + "-display");
        if (!el) return;
        if (!data || Object.keys(data).length === 0) {
            el.innerHTML = '<p style="color:var(--color-text-muted);">No information added yet.</p>';
            return;
        }
        var html = '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:var(--space-2);font-size:14px;">';
        fields.forEach(function (f) {
            var val = data[f[0]];
            if (f[2]) val = f[2](val);
            if (val) {
                html += '<div><strong>' + f[1] + ':</strong> ' + escapeHtml(val) + "</div>";
            }
        });
        html += "</div>";
        el.innerHTML = html;
    }

    function renderSkillTags(skills) {
        var el = document.querySelector(".key-skills-display");
        if (!el) return;
        if (!skills || skills.length === 0) {
            el.innerHTML = '<p style="color:var(--color-text-muted);">No key skills added.</p>';
            return;
        }
        var tags = skills.map(function (s) {
            return '<span class="ds-chip">' + escapeHtml(s.skill_name || "") + '</span>';
        }).join("");
        el.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:var(--space-1);">' + tags + "</div>";
    }

    function updateSkillCount() {
        var el = document.getElementById("key-skills-count");
        if (el) el.textContent = state.skillTags.length + " skill" + (state.skillTags.length !== 1 ? "s" : "");
    }

    function renderCompleteness(pct) {
        var ring = document.getElementById("completeness-ring");
        var text = document.getElementById("completeness-text");
        if (ring) ring.style.setProperty("--progress", pct);
        if (text) text.textContent = pct + "%";
    }

    // --- Edit mode toggle ---
    function toggleSectionEdit(section) {
        var displayEl = document.getElementById(section + "-display");
        var editEl = document.getElementById(section + "-edit");
        var btn = document.getElementById("btn-edit-" + section);
        if (!displayEl || !editEl) return;
        if (editEl.style.display === "none") {
            displayEl.style.display = "none";
            editEl.style.display = "block";
            if (btn) btn.innerHTML = '<i class="fas fa-times"></i> Cancel';
            loadSectionEditData(section);
        } else {
            displayEl.style.display = "block";
            editEl.style.display = "none";
            if (btn) btn.innerHTML = '<i class="fas fa-edit"></i> Edit';
        }
    }

    async function loadSectionEditData(section) {
        // Pre-fill edit forms from current data
        var res = await fetch("/api/candidate/profile");
        var data = await res.json();
        if (section === "personal") {
            var pd = data.personal_details || {};
            el("personal-dob").value = formatDate(pd.date_of_birth);
            el("personal-gender").value = pd.gender || "";
            el("personal-nationality").value = pd.nationality || "";
            el("personal-location").value = pd.current_location || "";
            el("personal-address").value = pd.permanent_address || "";
            el("personal-pincode").value = pd.pincode || "";
            el("personal-marital").value = pd.marital_status || "";
        } else if (section === "preferences") {
            var pd = data.preferences || {};
            el("pref-industry").value = pd.current_industry || "";
            el("pref-role").value = pd.current_job_role || pd.current_role || "";
            el("pref-job-type").value = pd.desired_job_type || "";
            el("pref-notice").value = pd.notice_period || "";
            el("pref-ctc").value = pd.current_ctc || "";
            el("pref-expected-ctc").value = pd.expected_ctc || "";
            el("pref-locations").value = (data.preferred_locations || []).join(", ");
        }
    }

    function el(id) {
        return document.getElementById(id);
    }

    // --- Save singleton sections ---
    async function savePersonalDetails() {
        var payload = {
            date_of_birth: el("personal-dob").value || null,
            gender: el("personal-gender").value || null,
            marital_status: el("personal-marital").value || null,
            nationality: el("personal-nationality").value || null,
            current_location: el("personal-location").value || null,
            hometown: null,
            permanent_address: el("personal-address").value || null,
            pincode: el("personal-pincode").value || null,
        };
        try {
            var res = await fetch("/api/candidate/profile/personal", {
                method: "POST",
                body: JSON.stringify(payload)
            });
            var data = await res.json();
            if (data.success) {
                dashboardShared.showToast("Personal details saved", "success");
                toggleSectionEdit("personal");
                loadProfile();
            } else {
                dashboardShared.showToast(data.message || "Failed to save", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    async function savePreferences() {
        var payload = {
            current_industry: el("pref-industry").value || null,
            current_department: null,
            current_job_role: el("pref-role").value || null,
            desired_job_type: el("pref-job-type").value || null,
            desired_employment_type: null,
            preferred_shift: null,
            current_ctc: el("pref-ctc").value || null,
            expected_ctc: el("pref-expected-ctc").value || null,
            notice_period: el("pref-notice").value || null,
            open_to_relocate: false,
            preferred_locations: el("pref-locations").value ? el("pref-locations").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [],
        };
        try {
            var res = await fetch("/api/candidate/profile/preferences", {
                method: "POST",
                body: JSON.stringify(payload)
            });
            var data = await res.json();
            if (data.success) {
                dashboardShared.showToast("Preferences saved", "success");
                toggleSectionEdit("preferences");
                loadProfile();
            } else {
                dashboardShared.showToast(data.message || "Failed to save", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    async function saveSummary() {
        var txt = el("summary-text").value.trim();
        var count = el("summary-count");
        if (count) count.textContent = txt.length + " / 1000";
        try {
            var res = await fetch("/api/candidate/profile/summary", {
                method: "POST",
                body: JSON.stringify({ summary: txt })
            });
            var data = await res.json();
            if (data.success) {
                dashboardShared.showToast("Summary saved", "success");
                toggleSectionEdit("summary");
                loadProfile();
            } else {
                dashboardShared.showToast(data.message || "Failed to save", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    async function saveProfileSummary() {
        var txt = el("profile-summary-text").value.trim();
        try {
            var res = await fetch("/api/candidate/profile/summary", {
                method: "POST",
                body: JSON.stringify({ summary: txt })
            });
            var data = await res.json();
            if (data.success) {
                loadProfile();
            } else {
                dashboardShared.showToast(data.message || "Failed to save", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    function updateSummaryCount() {
        var txt = el("summary-text");
        var count = el("summary-count");
        if (txt && count) count.textContent = txt.value.length + " / 1000";
    }

    // --- Key Skills tag input ---
    async function loadSkillSuggestions() {
        try {
            var res = await fetch("/api/candidate/skills/suggestions");
            var data = await res.json();
            if (data.success) {
                state.skillSuggestions = data.skills || [];
                renderSkillSuggestions();
            }
        } catch (e) { /* silent */ }
    }

    function renderSkillSuggestions() {
        var container = document.getElementById("skill-suggestions");
        if (!container) return;
        container.innerHTML = state.skillSuggestions.map(function (s) {
            return '<span class="ds-chip" onclick="candidateProfile.addSkillTag(\'' + s + '\')">' + escapeHtml(s) + "</span>";
        }).join("");
    }

    function addSkillTag(name) {
        if (state.skillTags.indexOf(name) === -1) {
            state.skillTags.push(name);
            renderSkillChips();
            updateSkillCount();
        }
        var input = el("key-skills-text");
        if (input) input.value = "";
    }

    function renderSkillChips() {
        var container = document.getElementById("key-skills-input");
        if (!container) return;
        var chips = state.skillTags.map(function (tag, i) {
            return '<span class="ds-chip">' + escapeHtml(tag) +
                ' <button type="button" class="ds-chip-removable" onclick="candidateProfile.removeSkillTag(' + i + ')"><i class="fas fa-times"></i></button></span>';
        }).join("");
        container.innerHTML = chips + '<input type="text" id="key-skills-text" placeholder="Type and press Enter..." style="flex:1;min-width:150px;">';
        setupSkillInput();
    }

    function setupSkillInput() {
        var input = el("key-skills-text");
        if (!input) return;
        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                var val = input.value.trim();
                if (val) {
                    val.split(",").forEach(function (s) {
                        var trimmed = s.trim();
                        if (trimmed) addSkillTag(trimmed);
                    });
                }
            }
        });
    }

    function removeSkillTag(index) {
        state.skillTags.splice(index, 1);
        renderSkillChips();
        updateSkillCount();
    }

    function toggleKeySkillsEdit() {
        var display = document.getElementById("key-skills-display");
        var edit = document.getElementById("key-skills-edit");
        var btn = document.getElementById("btn-key-skills-edit");
        var input = document.getElementById("key-skills-text");
        if (input) input.focus();
        if (!display || !edit) return;
        if (edit.style.display === "none") {
            display.style.display = "none";
            edit.style.display = "block";
            if (btn) btn.innerHTML = '<i class="fas fa-times"></i> Cancel';
        } else {
            display.style.display = "block";
            edit.style.display = "none";
            if (btn) btn.innerHTML = '<i class="fas fa-edit"></i> Edit';
        }
    }

    async function saveKeySkills() {
        // Delete all existing, then insert all current
        try {
            var listRes = await fetch("/api/candidate/profile/items?section=key-skills");
            var listData = await listRes.json();
            if (listData.success) {
                for (var i = 0; i < listData.items.length; i++) {
                    await fetch("/api/candidate/profile/items/" + listData.items[i].id, {
                        method: "DELETE",
                        body: JSON.stringify({ section: "key-skills" })
                    });
                }
            }
            for (var j = 0; j < state.skillTags.length; j++) {
                await fetch("/api/candidate/profile/items", {
                    method: "POST",
                    body: JSON.stringify({ section: "key-skills", skill_name: state.skillTags[j] })
                });
            }
            dashboardShared.showToast("Skills saved", "success");
            toggleKeySkillsEdit();
            loadProfile();
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    // --- Generic item modal ---
    var SECTION_FIELDS = {
        "employment": [
            ["company_name", "Company Name", "text"],
            ["job_title", "Job Title", "text"],
            ["employment_type", "Employment Type", "select:Fresher,Full-time,Part-time,Contract,Internship,Other"],
            ["department", "Department", "text"],
            ["is_current", "Current Job", "checkbox"],
            ["start_date", "Start Date", "date"],
            ["end_date", "End Date", "date"],
            ["job_profile", "Job Profile", "textarea"],
            ["skills_used", "Skills Used", "text"],
            ["gross_salary", "Gross Salary", "text"],
            ["notice_period", "Notice Period", "text"],
        ],
        "education": [
            ["education_level", "Education Level", "select:Freshers,10th,12th,Bachelor's,Master's,PhD,Diploma,Other"],
            ["institute", "Institute", "text"],
            ["course_degree", "Course / Degree", "text"],
            ["specialization", "Specialization", "text"],
            ["course_type", "Course Type", "select:Full-time,Part-time,Online,Regular"],
            ["grading_system", "Grading System", "select:CGPA,Percentage,Grade"],
            ["grade_value", "Grade / CGPA / Percentage", "text"],
            ["year_of_passing", "Year of Passing", "number"],
        ],
        "it-skills": [
            ["skill_name", "Skill Name", "text"],
            ["version", "Version", "text"],
            ["last_used_year", "Last Used Year", "number"],
            ["experience_years", "Years Experience", "number"],
            ["experience_months", "Additional Months", "number"],
            ["proficiency", "Proficiency", "select:Beginner,Intermediate,Advanced,Expert"],
        ],
        "internships": [
            ["organization_name", "Organization", "text"],
            ["role_title", "Role Title", "text"],
            ["start_date", "Start Date", "date"],
            ["end_date", "End Date", "date"],
            ["is_current", "Currently Doing", "checkbox"],
            ["stipend", "Stipend", "text"],
            ["project_details", "Project Details", "textarea"],
            ["skills_used", "Skills Used", "text"],
        ],
        "projects": [
            ["title", "Project Title", "text"],
            ["client_name", "Client Name", "text"],
            ["is_confidential", "Confidential", "checkbox"],
            ["status", "Status", "select:Planning,In Progress,Completed,On Hold"],
            ["start_date", "Start Date", "date"],
            ["end_date", "End Date", "date"],
            ["role", "Role", "text"],
            ["team_size", "Team Size", "number"],
            ["project_details", "Project Details", "textarea"],
            ["technology_tags", "Technologies", "text"],
        ],
        "online-profiles": [
            ["platform", "Platform", "select:LinkedIn,Github,Portfolio,Blog,Other"],
            ["profile_url", "Profile URL", "text"],
        ],
        "work-samples": [
            ["title", "Title", "text"],
            ["url", "URL", "text"],
            ["description", "Description", "textarea"],
        ],
        "certifications": [
            ["name", "Certification Name", "text"],
            ["issuing_authority", "Issuing Authority", "text"],
            ["certificate_id", "Certificate ID", "text"],
            ["issue_date", "Issue Date", "date"],
            ["expiry_date", "Expiry Date", "date"],
            ["no_expiry", "No Expiry", "checkbox"],
            ["credential_url", "Credential URL", "text"],
        ],
        "publications": [
            ["title", "Title", "text"],
            ["publisher_journal", "Publisher / Journal", "text"],
            ["url", "URL", "text"],
            ["pub_date", "Publication Date", "date"],
            ["description", "Description", "textarea"],
        ],
        "presentations": [
            ["title", "Title", "text"],
            ["url", "URL", "text"],
            ["present_date", "Date", "date"],
        ],
        "patents": [
            ["title", "Title", "text"],
            ["patent_office", "Patent Office", "text"],
            ["status", "Status", "select:Filed,Published,Granted,Rejected"],
            ["patent_number", "Patent Number", "text"],
            ["patent_date", "Date", "date"],
            ["url", "URL", "text"],
        ],
        "competitive-exams": [
            ["exam_name", "Exam Name", "text"],
            ["score_percentile", "Score / Percentile", "text"],
            ["rank", "Rank", "text"],
            ["year", "Year", "number"],
        ],
        "academic-achievements": [
            ["title", "Title", "text"],
            ["description", "Description", "textarea"],
            ["year", "Year", "number"],
        ],
        "languages": [
            ["language", "Language", "text"],
            ["can_read", "Can Read", "checkbox"],
            ["can_write", "Can Write", "checkbox"],
            ["can_speak", "Can Speak", "checkbox"],
        ],
        "preferred-locations": [
            ["location", "Location", "text"],
        ],
    };

    function openItemModal(section, item) {
        state.currentEditSection = section;
        state.currentEditItem = item || null;
        var titleEl = document.getElementById("item-modal-title");
        var bodyEl = document.getElementById("item-modal-body");
        var saveBtn = document.getElementById("item-modal-save");
        if (titleEl) titleEl.textContent = item ? "Edit " + section : "Add " + section.replace(/-/g, " ");
        if (saveBtn) saveBtn.textContent = item ? "Update" : "Save";
        if (bodyEl) {
            bodyEl.innerHTML = "";
            var fields = SECTION_FIELDS[section] || [];
            fields.forEach(function (f) {
                var fieldName = f[0];
                var label = f[1];
                var type = f[2] || "text";
                var row = document.createElement("div");
                row.style.marginBottom = "16px";
                var labelEl = document.createElement("label");
                labelEl.className = "ds-label";
                labelEl.textContent = label;
                var input;
                if (type === "textarea") {
                    input = document.createElement("textarea");
                    input.className = "ds-textarea";
                    input.rows = 3;
                } else if (type === "checkbox") {
                    input = document.createElement("input");
                    input.type = "checkbox";
                    input.id = "item-" + fieldName;
                    row.style.display = "flex";
                    row.style.alignItems = "center";
                    row.style.gap = "8px";
                    row.style.marginBottom = "12px";
                    var checkboxLabel = document.createElement("label");
                    checkboxLabel.textContent = label;
                    checkboxLabel.htmlFor = input.id;
                    checkboxLabel.style.margin = "0";
                    row.innerHTML = "";
                    row.appendChild(input);
                    row.appendChild(checkboxLabel);
                } else if (type.startsWith("select")) {
                    var options = type.substring(type.indexOf(":") + 1).split(",");
                    input = document.createElement("select");
                    input.className = "ds-select";
                    options.forEach(function (opt) {
                        var optEl = document.createElement("option");
                        optEl.value = opt;
                        optEl.textContent = opt;
                        input.appendChild(optEl);
                    });
                } else {
                    input = document.createElement("input");
                    input.type = type;
                    input.className = "ds-input";
                }
                input.id = "item-" + fieldName;
                if (item) {
                    if (input.type === "checkbox") {
                        input.checked = !!item[fieldName];
                    } else if (input.type === "number") {
                        input.value = item[fieldName] || "";
                    } else if (input.type === "date") {
                        if (item[fieldName]) {
                            var d = new Date(item[fieldName]);
                            if (!isNaN(d.getTime())) input.value = d.toISOString().split("T")[0];
                        }
                    } else {
                        input.value = item[fieldName] || "";
                    }
                }
                if (type !== "checkbox") row.appendChild(labelEl);
                row.appendChild(input);
                bodyEl.appendChild(row);
            });
        }
        var modal = document.getElementById("item-modal");
        if (modal) modal.classList.add("show");
    }

    function closeItemModal() {
        var modal = document.getElementById("item-modal");
        if (modal) modal.classList.remove("show");
    }

    function getItemFormData() {
        var fields = SECTION_FIELDS[state.currentEditSection] || [];
        var obj = {};
        fields.forEach(function (f) {
            var fieldName = f[0];
            var type = f[2] || "text";
            var input = el("item-" + fieldName);
            if (!input) { obj[fieldName] = null; return; }
            if (type === "checkbox") {
                obj[fieldName] = input.checked ? 1 : 0;
            } else if (type === "number") {
                obj[fieldName] = input.value ? parseInt(input.value, 10) : null;
            } else {
                obj[fieldName] = input.value || null;
            }
        });
        return obj;
    }

    async function saveItemModal() {
        var payload = getItemFormData();
        payload.section = state.currentEditSection;
        try {
            var url, method;
            if (state.currentEditItem) {
                url = "/api/candidate/profile/items/" + state.currentEditItem.id;
                method = "PUT";
            } else {
                url = "/api/candidate/profile/items";
                method = "POST";
            }
            var res = await fetch(url, {
                method: method,
                body: JSON.stringify(payload)
            });
            var data = await res.json();
            if (data.success) {
                dashboardShared.showToast(data.message || (state.currentEditItem ? "Updated" : "Added"), "success");
                closeItemModal();
                loadProfile();
            } else {
                dashboardShared.showToast(data.message || "Failed to save", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    function editItem(id, section) {
        loadItemForEdit(id, section);
    }

    async function loadItemForEdit(id, section) {
        try {
            var res = await fetch("/api/candidate/profile/items/" + section);
            var data = await res.json();
            if (data.success) {
                var items = data.items || [];
                for (var i = 0; i < items.length; i++) {
                    if (items[i].id == id) {
                        openItemModal(section, items[i]);
                        return;
                    }
                }
                dashboardShared.showToast("Item not found", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    async function deleteItem(id, section) {
        if (!confirm("Delete this entry?")) return;
        try {
            var res = await fetch("/api/candidate/profile/items/" + id, {
                method: "DELETE",
                body: JSON.stringify({ section: section })
            });
            var data = await res.json();
            if (data.success) {
                dashboardShared.showToast("Deleted", "success");
                loadProfile();
            } else {
                dashboardShared.showToast(data.message || "Failed to delete", "error");
            }
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    // --- Headline save ---
    async function saveProfileField(field) {
        var el = document.getElementById("profile-headline");
        if (!el) return;
        var headline = el.value.trim();
        try {
            // Use the legacy update endpoint for headline
            var res = await fetch("/api/candidate/profile", {
                method: "POST",
                body: JSON.stringify({ headline: headline })
            });
            var data = await res.json();
            if (!data.success) dashboardShared.showToast(data.message || "Failed to save", "error");
        } catch (e) {
            dashboardShared.showToast(e.message, "error");
        }
    }

    // --- Photo upload ---
    function handlePhotoUpload(event) {
        var file = event.target.files[0];
        if (!file) return;
        // Validate
        var IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp"];
        var ext = file.name.split(".").pop().toLowerCase();
        if (IMAGE_EXTENSIONS.indexOf(ext) === -1) {
            dashboardShared.showToast("Invalid image type", "error");
            return;
        }
        if (file.size > 2 * 1024 * 1024) {
            dashboardShared.showToast("Image too large (max 2MB)", "error");
            return;
        }
        var reader = new FileReader();
        reader.onload = function (e) {
            state.photoDataUrl = e.target.result;
            // Only open the modal if not already open
            var modal = document.getElementById("photo-modal");
            if (modal && modal.classList.contains("show")) {
                showPhotoPreview();
            } else {
                openPhotoModal();
            }
        };
        reader.readAsDataURL(file);
    }

    function openPhotoModal() {
        var modal = document.getElementById("photo-modal");
        if (modal) modal.classList.add("show");
        showPhotoPreview();
    }

    function showPhotoPreview() {
        var preview = document.getElementById("photo-preview");
        var placeholder = document.getElementById("photo-preview-placeholder");
        if (preview && state.photoDataUrl) {
            preview.src = state.photoDataUrl;
            preview.style.display = "block";
            if (placeholder) placeholder.style.display = "none";
            var saveBtn = document.getElementById("photo-save-btn");
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    function closePhotoModal() {
        var modal = document.getElementById("photo-modal");
        if (modal) modal.classList.remove("show");
    }

    function uploadPhoto() {
        if (!state.photoDataUrl) return;
        // Convert data URL to blob and upload via FormData
        var parts = state.photoDataUrl.split(";base64,");
        var contentType = parts[0].split(":")[1];
        var byteCharacters = atob(parts[1]);
        var byteNumbers = new Array(byteCharacters.length);
        for (var i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        var byteArray = new Uint8Array(byteNumbers);
        var blob = new Blob([byteArray], { type: contentType });
        var formData = new FormData();
        formData.append("photo", blob, "profile_photo.jpg");
        var uploadInput = el("photo-upload");
        if (uploadInput) uploadInput.value = "";

        fetch("/api/candidate/profile/photo", {
            method: "POST",
            body: formData
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.success) {
                dashboardShared.showToast("Photo uploaded", "success");
                closePhotoModal();
                loadProfile();
                state.photoDataUrl = null;
            } else {
                dashboardShared.showToast(data.message || "Upload failed", "error");
            }
        }).catch(function (e) {
            dashboardShared.showToast(e.message, "error");
        });
    }

    // --- Resume upload ---
    function handleResumeUpload(event) {
        var file = event.target.files[0];
        if (!file) return;
        var formData = new FormData();
        formData.append("resume", file);
        var container = document.getElementById("resume-skills");
        var tagsContainer = document.getElementById("resume-skills-tags");
        var resumeDisplay = document.getElementById("resume-display");
        if (container) container.style.display = "none";
        if (tagsContainer) tagsContainer.innerHTML = "";

        fetch("/api/candidate/profile/resume", {
            method: "POST",
            body: formData
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.success) {
                dashboardShared.showToast("Resume uploaded. " + (data.skills ? data.skills.length : 0) + " skills extracted.", "success");
                if (data.skills && data.skills.length > 0) {
                    if (container) container.style.display = "block";
                    if (tagsContainer) {
                        tagsContainer.innerHTML = data.skills.map(function (s) {
                            return '<span class="ds-chip">' + escapeHtml(s) + "</span>";
                        }).join("");
                    }
                }
                if (data.resume_path && resumeDisplay) {
                    var filename = data.resume_path.split('/').pop();
                    resumeDisplay.innerHTML = '<a href="/candidate/resume/download" class="btn btn-primary btn-sm" style="display:inline-block;"><i class="fas fa-download"></i> Download ' + escapeHtml(filename) + '</a>';
                }
            } else {
                dashboardShared.showToast(data.message || "Upload failed", "error");
            }
        }).catch(function (e) {
            dashboardShared.showToast(e.message, "error");
        });
    }

    // --- Init ---
    function init() {
        loadProfile();
        loadSkillSuggestions();
        var summaryInput = el("summary-text");
        if (summaryInput) summaryInput.addEventListener("input", updateSummaryCount);
    }

    // Expose to global scope for inline onclick handlers
    return {
        init: init,
        loadProfile: loadProfile,
        toggleSectionEdit: toggleSectionEdit,
        openItemModal: openItemModal,
        closeItemModal: closeItemModal,
        saveItemModal: saveItemModal,
        editItem: editItem,
        deleteItem: deleteItem,
        addSkillTag: addSkillTag,
        removeSkillTag: removeSkillTag,
        saveKeySkills: saveKeySkills,
        toggleKeySkillsEdit: toggleKeySkillsEdit,
        savePersonalDetails: savePersonalDetails,
        savePreferences: savePreferences,
        saveSummary: saveSummary,
        saveProfileSummary: saveProfileSummary,
        updateSummaryCount: updateSummaryCount,
        handlePhotoUpload: handlePhotoUpload,
        openPhotoModal: openPhotoModal,
        closePhotoModal: closePhotoModal,
        uploadPhoto: uploadPhoto,
        handleResumeUpload: handleResumeUpload,
        saveProfileField: saveProfileField,
        showPhotoPreview: showPhotoPreview,
    };
})();

// Auto-init
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", window.candidateProfile.init);
} else {
    window.candidateProfile.init();
}

// Expose functions as globals for inline onclick handlers in HTML
window.toggleSectionEdit = window.candidateProfile.toggleSectionEdit;
window.openItemModal = window.candidateProfile.openItemModal;
window.closeItemModal = window.candidateProfile.closeItemModal;
window.saveItemModal = window.candidateProfile.saveItemModal;
window.editItem = window.candidateProfile.editItem;
window.deleteItem = window.candidateProfile.deleteItem;
window.saveKeySkills = window.candidateProfile.saveKeySkills;
window.toggleKeySkillsEdit = window.candidateProfile.toggleKeySkillsEdit;
window.savePersonalDetails = window.candidateProfile.savePersonalDetails;
window.savePreferences = window.candidateProfile.savePreferences;
window.saveSummary = window.candidateProfile.saveSummary;
window.saveProfileSummary = window.candidateProfile.saveSummary;
window.addSkillTag = window.candidateProfile.addSkillTag;
window.removeSkillTag = window.candidateProfile.removeSkillTag;
window.handlePhotoUpload = window.candidateProfile.handlePhotoUpload;
window.previewPhoto = window.candidateProfile.handlePhotoUpload;
window.closePhotoModal = window.candidateProfile.closePhotoModal;
window.uploadPhoto = window.candidateProfile.uploadPhoto;
window.handleResumeUpload = window.candidateProfile.handleResumeUpload;
window.saveProfileSummary = window.candidateProfile.saveProfileSummary;
window.saveProfileField = window.candidateProfile.saveProfileField;
window.showPhotoPreview = window.candidateProfile.showPhotoPreview;
