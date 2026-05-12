import SwiftUI

struct ReviewTrainingView: View {
    private let legacyArchiveAPIBaseURL = "https://signomat-api.burgat-james.workers.dev"
    private let canonicalArchiveAPIBaseURL = "https://signs.jamesburgat.com"
    @StateObject private var viewModel = ArchiveAdminViewModel()
    @AppStorage("archiveAPIBaseURL") private var archiveAPIBaseURL = "https://signs.jamesburgat.com"
    @AppStorage("archiveAdminToken") private var archiveAdminToken = ""
    @State private var draftName = ""
    @State private var selectedModelType: ArchiveTrainingModelType = .detector
    @State private var selectedTripID = ""
    @State private var selectedReviewState: ArchiveReviewState = .reviewed
    @State private var includeFalsePositives = true
    @State private var trainingNotes = ""
    @State private var editingDetection: ArchiveDetection?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    apiCard
                    summaryCard
                    reviewQueueCard
                    trainingDraftCard
                    trainingJobsCard
                }
                .padding(20)
            }
            .navigationTitle("Sign Review")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Refresh") {
                        Task {
                            await viewModel.reload(apiBaseURLString: archiveAPIBaseURL, adminToken: archiveAdminToken)
                        }
                    }
                    .disabled(viewModel.isLoading)
                }
            }
            .task {
                migrateArchiveAPIBaseURLIfNeeded()
                await viewModel.reload(apiBaseURLString: archiveAPIBaseURL, adminToken: archiveAdminToken)
            }
            .sheet(item: $editingDetection) { detection in
                DetectionReviewEditor(
                    detection: detection,
                    saveAction: { updatedDetection in
                        await viewModel.updateReview(
                            apiBaseURLString: archiveAPIBaseURL,
                            adminToken: archiveAdminToken,
                            eventID: updatedDetection.eventID,
                            request: ArchiveReviewUpdateRequest(
                                reviewState: updatedDetection.reviewState,
                                notes: updatedDetection.notes,
                                categoryLabel: updatedDetection.categoryLabel,
                                specificLabel: updatedDetection.specificLabel
                            )
                        )
                    }
                )
            }
        }
    }

    private var apiCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Archive API")
                .font(.headline)

            Text("Use the same archive worker that powers site review and training drafts. This tab lets you confirm signs and queue new model-training exports without leaving the app.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            TextField("Archive API URL", text: $archiveAPIBaseURL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .textFieldStyle(.roundedBorder)

            SecureField("Admin token", text: $archiveAdminToken)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)

            HStack(spacing: 10) {
                Button("Reload Review Queue") {
                    Task {
                        await viewModel.reload(apiBaseURLString: archiveAPIBaseURL, adminToken: archiveAdminToken)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.isLoading)

                if let statusMessage = viewModel.statusMessage {
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private func migrateArchiveAPIBaseURLIfNeeded() {
        let trimmed = archiveAPIBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == legacyArchiveAPIBaseURL {
            archiveAPIBaseURL = canonicalArchiveAPIBaseURL
        }
    }

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Current YOLO Precision")
                .font(.headline)

            VStack(alignment: .leading, spacing: 10) {
                Text(precisionTitle)
                    .font(.title2)
                    .fontWeight(.bold)
                Text("Estimate is based only on detections you’ve reviewed as confirmed signs or false positives.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    metricTile(title: "Reviewed Sample", value: "\(viewModel.modelMetrics.reviewedSampleSize)")
                    metricTile(title: "Confirmed Signs", value: "\(viewModel.modelMetrics.confirmedSignCount)")
                    metricTile(title: "False Positives", value: "\(viewModel.modelMetrics.falsePositiveCount)")
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var trainingDraftCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Training Drafts")
                .font(.headline)

            Text("This is secondary here. Use it when you want to hand reviewed data back to the code-driven training pipeline.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            TextField("Draft name (optional)", text: $draftName)
                .textFieldStyle(.roundedBorder)

            Picker("Model Type", selection: $selectedModelType) {
                ForEach(ArchiveTrainingModelType.allCases) { modelType in
                    Text(modelType.rawValue.capitalized).tag(modelType)
                }
            }
            .pickerStyle(.segmented)

            Picker("Trip Scope", selection: $selectedTripID) {
                Text("All reviewed trips").tag("")
                ForEach(viewModel.trips) { trip in
                    Text(trip.tripId).tag(trip.tripId)
                }
            }

            Picker("Review State", selection: $selectedReviewState) {
                ForEach(ArchiveReviewState.writableCases) { state in
                    Text(state.title).tag(state)
                }
            }
            .pickerStyle(.segmented)

            Toggle("Include false positives", isOn: $includeFalsePositives)

            TextField("Notes", text: $trainingNotes, axis: .vertical)
                .lineLimit(3...6)
                .textFieldStyle(.roundedBorder)

            Button("Create Draft") {
                Task {
                    await viewModel.createTrainingJob(
                        apiBaseURLString: archiveAPIBaseURL,
                        adminToken: archiveAdminToken,
                        request: ArchiveTrainingJobCreateRequest(
                            name: draftName.trimmedNilIfEmpty,
                            modelType: selectedModelType,
                            tripId: selectedTripID.trimmedNilIfEmpty,
                            reviewState: selectedReviewState,
                            includeFalsePositives: includeFalsePositives,
                            notes: trainingNotes.trimmedNilIfEmpty
                        )
                    )
                    draftName = ""
                    trainingNotes = ""
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var reviewQueueCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Image Review Queue")
                    .font(.headline)
                Spacer()
                Text("\(viewModel.reviewQueue.count)")
                    .font(.headline)
            }

            if viewModel.reviewQueue.isEmpty {
                Text("No review items loaded yet.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(viewModel.reviewQueue) { detection in
                    DetectionReviewCard(
                        detection: detection,
                        markConfirmed: {
                            Task {
                                await viewModel.quickUpdateReview(
                                    apiBaseURLString: archiveAPIBaseURL,
                                    adminToken: archiveAdminToken,
                                    detection: detection,
                                    reviewState: .reviewed
                                )
                            }
                        },
                        markFalsePositive: {
                            Task {
                                await viewModel.quickUpdateReview(
                                    apiBaseURLString: archiveAPIBaseURL,
                                    adminToken: archiveAdminToken,
                                    detection: detection,
                                    reviewState: .falsePositive
                                )
                            }
                        },
                        editAction: {
                            editingDetection = detection
                        }
                    )
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var trainingJobsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Existing Drafts")
                .font(.headline)

            if viewModel.trainingJobs.isEmpty {
                Text("No training drafts yet.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(viewModel.trainingJobs) { job in
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(job.name)
                                    .fontWeight(.semibold)
                                Text(job.modelType.rawValue.capitalized)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text("\(job.selectedCount) items")
                                .font(.caption)
                                .fontWeight(.semibold)
                        }

                        Text(job.reviewState.title + (job.includeFalsePositives ? " + negatives" : ""))
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        if let suggestedCommand = job.suggestedCommand {
                            Text(suggestedCommand)
                                .font(.caption)
                                .textSelection(.enabled)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.secondary.opacity(0.08))
                                .clipShape(RoundedRectangle(cornerRadius: 12))
                        }

                        if let exportURL = job.exportUrl, let url = URL(string: exportURL) {
                            Link("Open Export", destination: url)
                                .font(.caption)
                        }
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.secondary.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }

    private var precisionTitle: String {
        guard let precision = viewModel.modelMetrics.reviewedPrecisionEstimate else {
            return "Review more images to measure sign precision."
        }
        return String(format: "%.1f%% sign precision on reviewed samples", precision * 100)
    }

    private func metricTile(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title2)
                .fontWeight(.bold)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}

private struct DetectionReviewCard: View {
    let detection: ArchiveDetection
    let markConfirmed: () -> Void
    let markFalsePositive: () -> Void
    let editAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                DetectionReviewPreview(detection: detection)

                VStack(alignment: .leading, spacing: 6) {
                    Text(detection.specificLabel ?? detection.categoryLabel)
                        .fontWeight(.semibold)
                    Text(detection.tripId)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(detection.timestampUtc)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 10) {
                        Label(detection.reviewState.title, systemImage: "tag")
                        if let confidence = detection.detectorConfidence {
                            Text(String(format: "Det %.0f%%", confidence * 100))
                        }
                        if let confidence = detection.classifierConfidence {
                            Text(String(format: "Cls %.0f%%", confidence * 100))
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 10) {
                Button("Confirm Sign", action: markConfirmed)
                    .buttonStyle(.borderedProminent)
                    .tint(.green)

                Button("Not a Sign", action: markFalsePositive)
                    .buttonStyle(.borderedProminent)
                    .tint(.red)

                Button("Edit", action: editAction)
                    .buttonStyle(.bordered)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }
}

private struct DetectionReviewEditor: View {
    @Environment(\.dismiss) private var dismiss

    let detection: ArchiveDetection
    let saveAction: (ArchiveDetection) async -> Bool

    @State private var draft: ArchiveDetection
    @State private var isSaving = false

    init(detection: ArchiveDetection, saveAction: @escaping (ArchiveDetection) async -> Bool) {
        self.detection = detection
        self.saveAction = saveAction
        var initialDraft = detection
        if !initialDraft.reviewState.isWritable {
            initialDraft.reviewState = .unreviewed
        }
        _draft = State(initialValue: initialDraft)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Review State") {
                    Picker("State", selection: $draft.reviewState) {
                        ForEach(ArchiveReviewState.writableCases) { state in
                            Text(state.title).tag(state)
                        }
                    }
                    .pickerStyle(.segmented)

                    if !detection.reviewState.isWritable {
                        Text("This item was machine classified by the archive. Saving here will convert it to a manual review state.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Labels") {
                    TextField("Category Label", text: $draft.categoryLabel)
                    TextField("Specific Label", text: Binding(
                        get: { draft.specificLabel ?? "" },
                        set: { draft.specificLabel = $0.trimmedNilIfEmpty }
                    ))
                }

                Section("Notes") {
                    TextField("Notes", text: Binding(
                        get: { draft.notes ?? "" },
                        set: { draft.notes = $0.trimmedNilIfEmpty }
                    ), axis: .vertical)
                    .lineLimit(4...8)
                }
            }
            .navigationTitle("Edit Review")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(isSaving ? "Saving..." : "Save") {
                        Task {
                            isSaving = true
                            let didSave = await saveAction(draft)
                            isSaving = false
                            if didSave {
                                dismiss()
                            }
                        }
                    }
                    .disabled(isSaving)
                }
            }
        }
    }
}

private extension String {
    var trimmedNilIfEmpty: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
