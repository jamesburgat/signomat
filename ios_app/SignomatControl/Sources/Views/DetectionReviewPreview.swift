import SwiftUI
import UIKit
import ImageIO
import UniformTypeIdentifiers

struct DetectionReviewPreview: View {
    let detection: ArchiveDetection

    @StateObject private var cropLoader = DetectionCropPreviewLoader()

    private let primarySize = CGSize(width: 132, height: 100)
    private let secondarySize = CGSize(width: 52, height: 40)

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            primaryPreview
                .frame(width: primarySize.width, height: primarySize.height)
                .clipShape(RoundedRectangle(cornerRadius: 14))

            if shouldShowSecondaryContext, let contextURL = detection.secondaryContextImageURL {
                RemoteReviewImage(url: contextURL, placeholder: placeholderImage)
                    .frame(width: secondarySize.width, height: secondarySize.height)
                    .background(.thinMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color.white.opacity(0.85), lineWidth: 1)
                    )
                    .padding(6)
            }
        }
        .frame(width: primarySize.width, height: primarySize.height)
        .task(id: detection.eventID) {
            await cropLoader.load(for: detection)
        }
    }

    @ViewBuilder
    private var primaryPreview: some View {
        if let url = detection.persistedCropPreviewURL {
            RemoteReviewImage(url: url, placeholder: placeholderImage)
        } else if let image = cropLoader.renderedImage {
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
        } else if cropLoader.isLoadingClientCrop {
            placeholderImage
        } else if let url = detection.framePreviewFallbackURL {
            RemoteReviewImage(url: url, placeholder: placeholderImage)
        } else {
            placeholderImage
        }
    }

    private var shouldShowSecondaryContext: Bool {
        switch primaryPreviewMode {
        case .persistedCrop(let primaryURL):
            guard let contextURL = detection.secondaryContextImageURL else { return false }
            return contextURL != primaryURL
        case .renderedCrop:
            return detection.secondaryContextImageURL != nil
        case .fallbackFrame, .placeholder:
            return false
        }
    }

    private var primaryPreviewMode: PrimaryPreviewMode {
        if let url = detection.persistedCropPreviewURL {
            return .persistedCrop(url)
        }
        if cropLoader.renderedImage != nil {
            return .renderedCrop
        }
        if let url = detection.framePreviewFallbackURL, cropLoader.isLoadingClientCrop == false {
            return .fallbackFrame(url)
        }
        return .placeholder
    }

    private var placeholderImage: some View {
        ZStack {
            Color.secondary.opacity(0.15)
            VStack(spacing: 6) {
                Image(systemName: "photo")
                    .foregroundStyle(.secondary)
                Text("No Cloudflare image")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private enum PrimaryPreviewMode {
    case persistedCrop(URL)
    case renderedCrop
    case fallbackFrame(URL)
    case placeholder
}

private struct RemoteReviewImage<Placeholder: View>: View {
    let url: URL
    let placeholder: Placeholder

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case .empty:
                placeholder
            case .success(let image):
                image
                    .resizable()
                    .scaledToFill()
            case .failure:
                placeholder
            @unknown default:
                placeholder
            }
        }
    }
}

@MainActor
private final class DetectionCropPreviewLoader: ObservableObject {
    @Published private(set) var renderedImage: UIImage?
    @Published private(set) var isLoadingClientCrop = false

    private var lastRequestKey: String?
    private var lastLoadFailed = false

    func load(for detection: ArchiveDetection) async {
        guard detection.persistedCropPreviewURL == nil else {
            reset()
            return
        }

        guard let request = detection.clientSideCropRequest else {
            reset()
            return
        }

        if lastRequestKey == request.identity && (renderedImage != nil || lastLoadFailed || isLoadingClientCrop) {
            return
        }

        lastRequestKey = request.identity
        lastLoadFailed = false
        renderedImage = nil
        isLoadingClientCrop = true

        do {
            let renderedData = try await DetectionCropRenderer.renderCropData(for: request)
            guard Task.isCancelled == false else { return }
            guard let image = UIImage(data: renderedData) else {
                lastLoadFailed = true
                isLoadingClientCrop = false
                return
            }
            renderedImage = image
            isLoadingClientCrop = false
        } catch is CancellationError {
            isLoadingClientCrop = false
        } catch {
            lastLoadFailed = true
            isLoadingClientCrop = false
        }
    }

    private func reset() {
        renderedImage = nil
        isLoadingClientCrop = false
        lastRequestKey = nil
        lastLoadFailed = false
    }
}

struct DetectionCropRequest: Hashable {
    let cacheKey: String
    let sourceURL: URL
    let bboxLeft: Double
    let bboxTop: Double
    let bboxRight: Double
    let bboxBottom: Double

    var identity: String {
        "\(cacheKey)|\(sourceURL.absoluteString)|\(bboxLeft)|\(bboxTop)|\(bboxRight)|\(bboxBottom)"
    }
}

private enum DetectionCropRenderer {
    private static let sourceDataCache = NSCache<NSURL, NSData>()
    private static let croppedDataCache = NSCache<NSString, NSData>()

    static func renderCropData(for request: DetectionCropRequest) async throws -> Data {
        let cacheKey = request.identity as NSString
        if let cached = croppedDataCache.object(forKey: cacheKey) {
            return Data(referencing: cached)
        }

        let sourceData = try await fetchSourceData(from: request.sourceURL)
        let croppedData = try await Task.detached(priority: .userInitiated) {
            try cropImageData(sourceData, request: request)
        }.value

        croppedDataCache.setObject(croppedData as NSData, forKey: cacheKey)
        return croppedData
    }

    private static func fetchSourceData(from url: URL) async throws -> Data {
        if let cached = sourceDataCache.object(forKey: url as NSURL) {
            return Data(referencing: cached)
        }

        let (data, response) = try await URLSession.shared.data(from: url)
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw DetectionCropError.invalidResponse
        }

        sourceDataCache.setObject(data as NSData, forKey: url as NSURL)
        return data
    }

    private static func cropImageData(_ sourceData: Data, request: DetectionCropRequest) throws -> Data {
        guard
            let imageSource = CGImageSourceCreateWithData(sourceData as CFData, nil),
            let cgImage = CGImageSourceCreateImageAtIndex(imageSource, 0, nil)
        else {
            throw DetectionCropError.decodingFailed
        }

        guard let cropRect = cropRect(for: request, imageWidth: cgImage.width, imageHeight: cgImage.height) else {
            throw DetectionCropError.invalidBounds
        }

        guard let croppedCGImage = cgImage.cropping(to: cropRect) else {
            throw DetectionCropError.cropFailed
        }

        let output = NSMutableData()
        guard
            let destination = CGImageDestinationCreateWithData(output, UTType.png.identifier as CFString, 1, nil)
        else {
            throw DetectionCropError.encodingFailed
        }

        CGImageDestinationAddImage(destination, croppedCGImage, nil)
        guard CGImageDestinationFinalize(destination) else {
            throw DetectionCropError.encodingFailed
        }

        return output as Data
    }

    private static func cropRect(
        for request: DetectionCropRequest,
        imageWidth: Int,
        imageHeight: Int
    ) -> CGRect? {
        let bounds = CGRect(x: 0, y: 0, width: imageWidth, height: imageHeight)

        let left = max(bounds.minX, min(CGFloat(request.bboxLeft), bounds.maxX))
        let right = max(bounds.minX, min(CGFloat(request.bboxRight), bounds.maxX))
        let top = max(bounds.minY, min(CGFloat(request.bboxTop), bounds.maxY))
        let bottom = max(bounds.minY, min(CGFloat(request.bboxBottom), bounds.maxY))

        let minX = floor(min(left, right))
        let maxX = ceil(max(left, right))
        let minY = floor(min(top, bottom))
        let maxY = ceil(max(top, bottom))

        let clamped = CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
            .intersection(bounds)

        guard clamped.width >= 1, clamped.height >= 1 else { return nil }
        return clamped
    }
}

private enum DetectionCropError: Error {
    case invalidResponse
    case decodingFailed
    case invalidBounds
    case cropFailed
    case encodingFailed
}
