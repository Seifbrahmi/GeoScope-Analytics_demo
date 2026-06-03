var map = L.map("map").setView([40, -100], 4);

var apiBaseUrl = window.APP_CONFIG && typeof window.APP_CONFIG.apiBaseUrl === "string"
    ? window.APP_CONFIG.apiBaseUrl.replace(/\/+$/, "")
    : "http://127.0.0.1:5000";

function buildApiUrl(path) {
    return apiBaseUrl + path;
}

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

var MAP_PANES = {
    catchmentBoundaryPane: 250,
    lakesPane: 300,
    lakeCciChlaPane: 400,
    lakeCciLswtPane: 410,
    lakeCciTsmPane: 420,
    aodPane: 500,
    temperaturePane: 550,
    burnedPane: 600,
    selectedLakePane: 700,
    selectedCatchmentPane: 710
};

Object.keys(MAP_PANES).forEach(function (paneName) {
    if (!map.getPane(paneName)) {
        map.createPane(paneName);
    }
    map.getPane(paneName).style.zIndex = String(MAP_PANES[paneName]);
});

console.log("[pane_config]", MAP_PANES);

var catchmentsLayer = null;
var catchmentsGeoJsonData = null;
var selectedCatchmentLayer = null;
var resultsChart = null;
var activeCatchmentId = null;
var selectedLakeId = null;
var selectedLakeCatchmentId = null;
var selectedLakeLabel = null;
var currentResults = [];
var currentRequestId = 0;
var catchmentIdByOutlet = {};
var landCoverByCatchment = {};
var landcoverOverlay = null;
var landcoverLegend = null;
var burnedAreaOverlay = null;
var burnedAreaOverlayData = null;
var burnedAreaLegend = null;
var temperatureOverlay = null;
var temperatureOverlayData = null;
var temperatureLegend = null;
var aodOverlay = null;
var aodOverlayData = null;
var aodLegend = null;
var chlaOverlayData = null;
var lswtOverlayData = null;
var tsmOverlayData = null;
var chlaLayer = null;
var chlaLegend = null;
var lswtLayer = null;
var lswtLegend = null;
var tsmLayer = null;
var tsmLegend = null;
var lakesLayer = null;
var lakesGeoJsonData = null;
var lakesOverviewLayer = null;
var selectedLakeHighlightLayer = null;
var hasCompletedAnalysis = false;
var analysisIsLoading = false;

var appShell = document.querySelector(".app-shell");
var controlPanel = document.getElementById("control-panel");
var toggleControlsButton = document.getElementById("toggle-controls");
var catchmentSelect = document.getElementById("catchmentSelect");
var startDateInput = document.getElementById("start-date");
var endDateInput = document.getElementById("end-date");
var aggregationSelect = document.getElementById("aggregationSelect");
var runButton = document.getElementById("run-analysis");
var resetAnalysisButton = document.getElementById("reset-analysis");
var burnedOverlayToggle = document.getElementById("toggle-burned-overlay");
var lakesLayerToggle = document.getElementById("toggle-lakes-layer");
var temperatureOverlayToggle = document.getElementById("toggle-temperature-overlay");
var aodOverlayToggle = document.getElementById("toggle-aod-overlay");
var chlaLayerToggle = document.getElementById("toggle-chla-layer");
var lswtLayerToggle = document.getElementById("toggle-lswt-layer");
var tsmLayerToggle = document.getElementById("toggle-tsm-layer");
var resultVariableInputs = Array.prototype.slice.call(document.querySelectorAll('input[name="result-variable"]'));
var exportButton = document.getElementById("export-csv");
var closeResultsButton = document.getElementById("close-results");
var resultsBackdrop = document.getElementById("results-backdrop");
var showMapButton = document.getElementById("show-map");
var showResultsButton = document.getElementById("show-results");
var tableContainer = document.getElementById("table-container");
var statisticsTableContainer = document.getElementById("statistics-table-container");
var resultsChartCanvas = document.getElementById("results-chart");
var resultsShell = document.getElementById("results-drawer");
var resultsTitle = document.getElementById("results-title");
var resultsPeriodIndicator = document.getElementById("results-period-indicator");
var resultsDebugMeta = document.getElementById("results-debug-meta");
var selectedLakeValue = document.getElementById("selected-lake-value");
var avgBurnedArea = document.getElementById("avg-burned-area");
var avgRainfall = document.getElementById("avg-rainfall");
var avgTemperature = document.getElementById("avg-temperature");
var avgAod = document.getElementById("avg-aod");
var avgChla = document.getElementById("avg-chla");
var avgLswt = document.getElementById("avg-lswt");
var avgTsm = document.getElementById("avg-tsm");
var medianBurnedArea = document.getElementById("median-burned-area");
var medianRainfall = document.getElementById("median-rainfall");
var medianTemperature = document.getElementById("median-temperature");
var medianAod = document.getElementById("median-aod");
var medianChla = document.getElementById("median-chla");
var medianLswt = document.getElementById("median-lswt");
var medianTsm = document.getElementById("median-tsm");
var stdBurnedArea = document.getElementById("std-burned-area");
var stdRainfall = document.getElementById("std-rainfall");
var stdTemperature = document.getElementById("std-temperature");
var stdAod = document.getElementById("std-aod");
var stdChla = document.getElementById("std-chla");
var stdLswt = document.getElementById("std-lswt");
var stdTsm = document.getElementById("std-tsm");
var dominantLandCover = document.getElementById("dominant-land-cover");
var lakeCoverage = document.getElementById("lake-coverage");
var waterInsight = document.getElementById("water-insight");
var variableCards = Array.prototype.slice.call(document.querySelectorAll("[data-variable-card]"));
var quickCatchment = document.getElementById("quick-catchment");
var quickWindow = document.getElementById("quick-window");
var quickRecords = document.getElementById("quick-records");
var statusDot = document.querySelector(".status-dot");
var chartTextColor = "#6b7280";
var chartGridColor = "rgba(203, 213, 225, 0.65)";
var chartFontFamily = "\"Manrope\", \"Segoe UI\", sans-serif";
var lastRequestedVariables = ["temperature", "rainfall", "aod", "burned_area", "chla", "lake_surface_water_temperature", "tsm"];
var lastRequestedAggregation = "monthly";
var hasAoiMapView = false;
var selectedLakeFeature = null;

var resultVariableConfig = {
    temperature: {
        label: "Temperature",
        overlayToggle: temperatureOverlayToggle
    },
    rainfall: {
        label: "Rainfall",
        overlayToggle: null
    },
    aod: {
        label: "AOD",
        overlayToggle: aodOverlayToggle
    },
    chla: {
        label: "Chlorophyll-a",
        overlayToggle: chlaLayerToggle
    },
    lake_surface_water_temperature: {
        label: "LSWT",
        overlayToggle: lswtLayerToggle
    },
    tsm: {
        label: "Turbidity",
        overlayToggle: tsmLayerToggle
    },
    burned_area: {
        label: "FireCCI / Burned Area",
        overlayToggle: burnedOverlayToggle
    }
};

var landCoverMap = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen"
};

var landCoverColors = {
    10: "#2e7d32",
    20: "#4d7c0f",
    30: "#84cc16",
    40: "#f9a825",
    50: "#616161",
    60: "#c2a878",
    70: "#dbeafe",
    80: "#42a5f5",
    90: "#14b8a6",
    95: "#0f766e",
    100: "#8d99ae"
};

function metersToMillimeters(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? null : numericValue * 1000;
}

function squareMetersToHectares(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? null : numericValue / 10000;
}

function formatLocaleNumber(value, minimumFractionDigits, maximumFractionDigits) {
    var numericValue = Number(value);

    if (isNaN(numericValue)) {
        return "--";
    }

    return numericValue.toLocaleString("en-US", {
        minimumFractionDigits: minimumFractionDigits,
        maximumFractionDigits: maximumFractionDigits
    });
}

function isTenDayAggregation() {
    return lastRequestedAggregation === "10days";
}

function formatBurnedAreaHectares(value) {
    var hectaresValue = squareMetersToHectares(value);

    if (hectaresValue === null) {
        return "--";
    }

    if (hectaresValue === 0) {
        return "0.00";
    }

    return formatLocaleNumber(hectaresValue, hectaresValue < 1 ? 4 : 2, hectaresValue < 1 ? 4 : 2);
}

function formatBurnedAreaHectaresPrecise(value) {
    var hectaresValue = squareMetersToHectares(value);
    return hectaresValue === null ? "--" : formatLocaleNumber(hectaresValue, 2, 4);
}

function formatTemperatureCelsius(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 2, 2);
}

function formatRainfallMillimeters(value) {
    var rainfallMillimeters = metersToMillimeters(value);
    return rainfallMillimeters === null ? "--" : formatLocaleNumber(rainfallMillimeters, 2, 2);
}

function formatAodValue(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 3, 3);
}

function formatChlaValue(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 2, 2);
}

function formatLswtValue(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 2, 2);
}

function formatTsmValue(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 2, 2);
}

function formatBurnedAreaHectaresDetailed(value) {
    var hectaresValue = squareMetersToHectares(value);
    return hectaresValue === null ? "--" : formatLocaleNumber(hectaresValue, 2, 4);
}

function formatRainfallMillimetersDetailed(value) {
    var rainfallMillimeters = metersToMillimeters(value);
    return rainfallMillimeters === null ? "--" : formatLocaleNumber(rainfallMillimeters, 3, 4);
}

function formatTemperatureDetailed(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 3, 4);
}

function formatAodDetailed(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 4, 4);
}

function formatChlaDetailed(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 3, 4);
}

function formatLswtDetailed(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 3, 4);
}

function formatTsmDetailed(value) {
    var numericValue = Number(value);
    return isNaN(numericValue) ? "--" : formatLocaleNumber(numericValue, 3, 4);
}

function formatVariableValue(variableKey, value, useDetailed) {
    if (variableKey === "burned_area") {
        return useDetailed ? formatBurnedAreaHectaresDetailed(value) : formatBurnedAreaHectares(value);
    }
    if (variableKey === "rainfall") {
        return useDetailed ? formatRainfallMillimetersDetailed(value) : formatRainfallMillimeters(value);
    }
    if (variableKey === "temperature") {
        return useDetailed ? formatTemperatureDetailed(value) : formatTemperatureCelsius(value);
    }
    if (variableKey === "aod") {
        return useDetailed ? formatAodDetailed(value) : formatAodValue(value);
    }
    if (variableKey === "chla") {
        return useDetailed ? formatChlaDetailed(value) : formatChlaValue(value);
    }
    if (variableKey === "lake_surface_water_temperature") {
        return useDetailed ? formatLswtDetailed(value) : formatLswtValue(value);
    }
    if (variableKey === "tsm") {
        return useDetailed ? formatTsmDetailed(value) : formatTsmValue(value);
    }
    return value === undefined || value === null || value === "" ? "--" : String(value);
}

function formatChartTooltipValue(datasetLabel, value) {
    if (value === null || value === undefined || isNaN(Number(value))) {
        return datasetLabel + ": --";
    }

    var numericValue = Number(value);

    if (datasetLabel.indexOf("Burned Area") !== -1) {
        return datasetLabel + ": " + formatLocaleNumber(numericValue, 2, 4);
    }

    if (datasetLabel.indexOf("Rainfall") !== -1) {
        return datasetLabel + ": " + formatLocaleNumber(numericValue, 3, 4);
    }

    return datasetLabel + ": " + formatLocaleNumber(numericValue, 3, 4);
}

function getLakeCciLayerConfig(variableKey) {
    if (variableKey === "chla") {
        return {
            title: "CHLA Layer",
            unit: "mg/m3",
            minLabel: "Low",
            maxLabel: "High",
            colors: ["#2563eb", "#22c55e", "#fde047", "#ef4444"]
        };
    }

    if (variableKey === "lake_surface_water_temperature") {
        return {
            title: "LSWT Layer",
            unit: "\u00B0C",
            minLabel: "Cold",
            maxLabel: "Warm",
            colors: ["#2563eb", "#22d3ee", "#fde047", "#f97316", "#dc2626"]
        };
    }

    if (variableKey === "tsm") {
        return {
            title: "Turbidity Layer",
            unit: "g/m3",
            minLabel: "Clear",
            maxLabel: "Turbid",
            colors: ["#dbeafe", "#d6c6a5", "#8b5a2b"]
        };
    }

    return null;
}

function interpolateHexColor(leftHex, rightHex, ratio) {
    function hexToRgb(hex) {
        var normalized = hex.replace("#", "");
        return {
            r: parseInt(normalized.slice(0, 2), 16),
            g: parseInt(normalized.slice(2, 4), 16),
            b: parseInt(normalized.slice(4, 6), 16)
        };
    }

    var left = hexToRgb(leftHex);
    var right = hexToRgb(rightHex);
    var clampedRatio = Math.max(0, Math.min(1, ratio));
    var red = Math.round(left.r + ((right.r - left.r) * clampedRatio));
    var green = Math.round(left.g + ((right.g - left.g) * clampedRatio));
    var blue = Math.round(left.b + ((right.b - left.b) * clampedRatio));

    return "rgb(" + red + ", " + green + ", " + blue + ")";
}

function getInterpolatedRampColor(colors, ratio) {
    if (!Array.isArray(colors) || !colors.length) {
        return "#1E90FF";
    }

    if (colors.length === 1) {
        return colors[0];
    }

    var clampedRatio = Math.max(0, Math.min(1, ratio));
    var scaled = clampedRatio * (colors.length - 1);
    var lowerIndex = Math.floor(scaled);
    var upperIndex = Math.min(colors.length - 1, lowerIndex + 1);
    var blend = scaled - lowerIndex;

    return interpolateHexColor(colors[lowerIndex], colors[upperIndex], blend);
}

function getSelectedResultVariables() {
    return resultVariableInputs
        .filter(function (input) {
            return input.checked;
        })
        .map(function (input) {
            return input.value;
        });
}

function hasSelectedResultVariable(variableKey, selectedVariables) {
    var variables = selectedVariables || getSelectedResultVariables();
    return variables.indexOf(variableKey) !== -1;
}

function enforceResultVariableSelection(changedInput) {
    var selectedVariables = getSelectedResultVariables();

    if (selectedVariables.length) {
        return true;
    }

    if (changedInput) {
        changedInput.checked = true;
    }

    setStatus("Select at least one result variable.", true);
    return false;
}

function updateRunButtonState() {
    runButton.disabled = analysisIsLoading || !selectedLakeId || !getSelectedResultVariables().length;
}

function setStatus(message, isError) {
    var status = document.getElementById("status-message");
    status.textContent = message;
    status.style.color = isError ? "#dc2626" : "#52606d";
    if (statusDot) {
        statusDot.style.background = isError ? "#dc2626" : "#10b981";
        statusDot.style.boxShadow = isError
            ? "0 0 0 6px rgba(220, 38, 38, 0.12)"
            : "0 0 0 6px rgba(16, 185, 129, 0.12)";
    }
}

function setLoadingState(isLoading) {
    analysisIsLoading = isLoading;
    updateRunButtonState();
    runButton.textContent = isLoading ? "Running..." : "Run Analysis";
}

function setSelectedLakeDisplay(label) {
    var displayLabel = label || "--";

    if (selectedLakeValue) {
        selectedLakeValue.textContent = displayLabel;
    }

    if (resultsTitle) {
        resultsTitle.textContent = label ? "Analysis for Selected Lake" : "Analysis for Selected Lake";
    }
}

function setResetButtonVisible(isVisible) {
    if (!resetAnalysisButton) {
        return;
    }

    resetAnalysisButton.classList.toggle("is-hidden", !isVisible);
}

function animateResultsShell() {
    if (!resultsShell) {
        return;
    }

    resultsShell.classList.remove("is-refreshed");
    void resultsShell.offsetWidth;
    resultsShell.classList.add("is-refreshed");
}

function formatDateWindow() {
    if (startDateInput.value && endDateInput.value) {
        return startDateInput.value + " to " + endDateInput.value + " (" + getSelectedAggregationLabel() + ")";
    }

    if (startDateInput.value) {
        return "From " + startDateInput.value + " (" + getSelectedAggregationLabel() + ")";
    }

    if (endDateInput.value) {
        return "Until " + endDateInput.value + " (" + getSelectedAggregationLabel() + ")";
    }

    return "--";
}

function getSelectedAggregationMode() {
    return aggregationSelect && aggregationSelect.value ? aggregationSelect.value : "monthly";
}

function getSelectedAggregationLabel() {
    var aggregationMode = getSelectedAggregationMode();

    if (aggregationMode === "10days") {
        return "10 Days";
    }

    if (aggregationMode === "weekly") {
        return "Weekly";
    }

    return "Monthly";
}

function updateResultsPeriodSummary(records) {
    if (!resultsPeriodIndicator || !resultsDebugMeta) {
        return;
    }

    var selectedDate = startDateInput && startDateInput.value ? startDateInput.value : "--";
    var effectiveRecordDate = records && records.length ? records[0].date : "--";
    var aggregationLabel = getSelectedAggregationLabel();

    resultsPeriodIndicator.textContent = "Selected Period: " + aggregationLabel;

    resultsDebugMeta.textContent =
        "Selected Date: " + selectedDate +
        " | Effective Record: " + effectiveRecordDate +
        " | Aggregation: " + aggregationLabel;
}

function logTemporalDebug(stage, payload) {
    if (!console || typeof console.log !== "function") {
        return;
    }

    console.log("[temporal_debug][" + stage + "]", payload);
}

function updateQuickStats(recordCount) {
    if (quickCatchment) {
        quickCatchment.textContent = catchmentSelect.value || "--";
    }

    if (quickWindow) {
        quickWindow.textContent = formatDateWindow();
    }

    if (!quickRecords) {
        return;
    }

    if (recordCount === null) {
        quickRecords.textContent = "--";
        return;
    }

    if (typeof recordCount === "number") {
        quickRecords.textContent = String(recordCount);
        return;
    }

    quickRecords.textContent = currentResults.length ? String(currentResults.length) : "--";
}

function setControlsCollapsed(isCollapsed) {
    if (!controlPanel || !toggleControlsButton) {
        return;
    }

    controlPanel.classList.toggle("is-collapsed", isCollapsed);
    controlPanel.setAttribute("aria-expanded", String(!isCollapsed));
    toggleControlsButton.setAttribute("aria-expanded", String(!isCollapsed));
    toggleControlsButton.textContent = isCollapsed ? "Show" : "Hide";

    window.setTimeout(function () {
        map.invalidateSize();
    }, 220);
}

function setResultsPanelOpen(isOpen) {
    if (!appShell || !resultsShell) {
        return;
    }

    appShell.classList.toggle("is-results-open", isOpen);
    resultsShell.setAttribute("aria-hidden", String(!isOpen));

    if (showMapButton) {
        showMapButton.classList.toggle("is-active", !isOpen);
    }

    if (showResultsButton) {
        showResultsButton.classList.toggle("is-active", isOpen);
    }

    window.setTimeout(function () {
        if (isOpen && resultsChart) {
            resultsChart.resize();
            return;
        }

        map.invalidateSize();
    }, 260);
}

function getMapFitOptions() {
    var rightPadding = 24;

    if (appShell && appShell.classList.contains("is-results-open") && window.innerWidth > 760) {
        rightPadding = Math.min(window.innerWidth * 0.38, 540) + 40;
    }

    return {
        paddingTopLeft: [32, 100],
        paddingBottomRight: [rightPadding, 48]
    };
}

function getFeatureCatchmentId(feature) {
    if (!feature || !feature.properties) {
        return null;
    }

    if (feature.properties.catchment_id !== undefined && feature.properties.catchment_id !== null && feature.properties.catchment_id !== "") {
        return String(feature.properties.catchment_id);
    }

    if (feature.properties.Outlet_id !== undefined && feature.properties.Outlet_id !== null) {
        return catchmentIdByOutlet[String(feature.properties.Outlet_id)] || null;
    }

    return null;
}

function getLandCoverValue(value) {
    if (value === undefined || value === null) {
        return null;
    }

    if (typeof value === "string" && value.trim() === "") {
        return null;
    }

    var landCoverValue = Number(value);
    return isNaN(landCoverValue) ? null : landCoverValue;
}

function getLandCoverLabel(value) {
    var landCoverValue = getLandCoverValue(value);
    return landCoverValue === null ? "Unknown" : (landCoverMap[landCoverValue] || "Unknown");
}

function logLandCoverValues(data) {
    var uniqueLandCoverValues = data
        .map(function (row) {
            return getLandCoverValue(row.land_cover);
        })
        .filter(function (value, index, values) {
            return value !== null && values.indexOf(value) === index;
        })
        .sort(function (a, b) {
            return a - b;
        });

    console.log("Unique land_cover values from API response:", uniqueLandCoverValues);

    var unmappedLandCoverValues = uniqueLandCoverValues.filter(function (value) {
        return !Object.prototype.hasOwnProperty.call(landCoverMap, value);
    });

    if (unmappedLandCoverValues.length) {
        console.warn("Unmapped land_cover values:", unmappedLandCoverValues);
    }
}

function getCatchmentFillColor(feature) {
    var landCoverValue = getLandCoverValue(feature.properties.land_cover);
    return landCoverColors[landCoverValue] || "#999";
}

function getFeatureStyle(feature) {
    return {
        color: "#334155",
        weight: 1.1,
        fillColor: getCatchmentFillColor(feature),
        fillOpacity: 0.48
    };
}

function getHoverStyle(feature) {
    return {
        color: "#7ce8ce",
        weight: 2,
        fillColor: getCatchmentFillColor(feature),
        fillOpacity: 0.68
    };
}

function getSelectedStyle(feature) {
    return {
        color: "#ff916b",
        weight: 3,
        fillColor: getCatchmentFillColor(feature),
        fillOpacity: 0.84
    };
}

function getLakeStyle() {
    return {
        color: "#1E90FF",
        weight: 1.1,
        fillColor: "#4aa8ff",
        fillOpacity: 0.5
    };
}

function getLakeHoverStyle() {
    return {
        color: "#0c6ed7",
        weight: 2,
        fillColor: "#4aa8ff",
        fillOpacity: 0.68
    };
}

function getSelectedLakeStyle() {
    return {
        color: "#0f4c81",
        weight: 2.4,
        fillColor: "#1E90FF",
        fillOpacity: 0.74
    };
}

function resetLayerStyle(layer) {
    var id = getFeatureCatchmentId(layer.feature);
    if (String(id) === String(activeCatchmentId)) {
        layer.setStyle(getSelectedStyle(layer.feature));
    } else {
        layer.setStyle(getFeatureStyle(layer.feature));
    }
}

function removeSelectedCatchmentLayer() {
    if (selectedCatchmentLayer) {
        map.removeLayer(selectedCatchmentLayer);
        selectedCatchmentLayer = null;
    }

    removeLandcoverLegend();
}

function showSelectedCatchment(feature, shouldFitBounds) {
    removeSelectedCatchmentLayer();

    if (!feature) {
        activeCatchmentId = null;
        return;
    }

    activeCatchmentId = getFeatureCatchmentId(feature);
    selectedCatchmentLayer = L.geoJSON(feature, {
        pane: "selectedCatchmentPane",
        style: function () {
            return {
                color: "#ff916b",
                weight: 3,
                fillColor: getCatchmentFillColor(feature),
                fillOpacity: 0.16
            };
        }
    }).addTo(map);

    syncLandcoverLegend();

    if (shouldFitBounds !== false) {
        map.fitBounds(selectedCatchmentLayer.getBounds(), getMapFitOptions());
    }
}

function findCatchmentFeatureById(id) {
    if (!catchmentsGeoJsonData || !catchmentsGeoJsonData.features) {
        return null;
    }

    for (var i = 0; i < catchmentsGeoJsonData.features.length; i += 1) {
        var feature = catchmentsGeoJsonData.features[i];
        if (String(getFeatureCatchmentId(feature)) === String(id)) {
            return feature;
        }
    }

    return null;
}

function highlightCatchment(id) {
    activeCatchmentId = id;
    var feature = findCatchmentFeatureById(id);
    if (!feature) {
        return;
    }

    showSelectedCatchment(feature, true);
}

function updateVariableCardVisibility(selectedVariables) {
    variableCards.forEach(function (card) {
        var variableKey = card.getAttribute("data-variable-card");
        card.classList.toggle("is-hidden", !hasSelectedResultVariable(variableKey, selectedVariables));
    });
}

function updateVariableOverlayToggleState(selectedVariables) {
    Object.keys(resultVariableConfig).forEach(function (variableKey) {
        var config = resultVariableConfig[variableKey];
        var toggle = config.overlayToggle;

        if (!toggle) {
            return;
        }

        var row = toggle.closest(".toggle-row");
        var isEnabled = hasSelectedResultVariable(variableKey, selectedVariables);

        toggle.disabled = !isEnabled;
        if (row) {
            row.classList.toggle("is-disabled", !isEnabled);
        }
    });
}

function applySelectedResultVariableView(options) {
    var selectedVariables = getSelectedResultVariables();
    var hasResults = options && options.hasResults;
    var shouldSyncOverlays = !options || options.syncOverlays !== false;

    updateVariableCardVisibility(selectedVariables);
    updateVariableOverlayToggleState(selectedVariables);

    if (!hasResults) {
        return;
    }

    updateSummary(currentResults, selectedVariables);
    renderChart(currentResults, selectedVariables);
    renderTable(currentResults, selectedVariables);
    renderStatisticsSummaryTable(currentResults, selectedVariables);

    if (shouldSyncOverlays) {
        syncBurnedAreaOverlay();
        syncTemperatureOverlay();
        syncAodOverlay();
        syncLakeIndicatorLayer("chla");
        syncLakeIndicatorLayer("lake_surface_water_temperature");
        syncLakeIndicatorLayer("tsm");
    }
}

function renderTable(data, selectedVariables) {
    if (!data.length) {
        tableContainer.innerHTML = '<p class="placeholder">No results returned for the selected filters.</p>';
        return;
    }

    logTemporalDebug("table_input", {
        aggregation: lastRequestedAggregation,
        selectedDateStart: startDateInput.value,
        selectedDateEnd: endDateInput.value,
        recordCount: data.length,
        dates: data.map(function (row) { return row.date; }),
        records: data
    });

    var columns = ["lake_id", "catchment_id", "date"];
    if (hasSelectedResultVariable("burned_area", selectedVariables)) {
        columns.push("burned_area");
    }
    if (hasSelectedResultVariable("rainfall", selectedVariables)) {
        columns.push("rainfall");
    }
    if (hasSelectedResultVariable("temperature", selectedVariables)) {
        columns.push("temperature");
    }
    if (hasSelectedResultVariable("aod", selectedVariables)) {
        columns.push("aod");
    }
    if (hasSelectedResultVariable("chla", selectedVariables)) {
        columns.push("chla");
    }
    if (hasSelectedResultVariable("lake_surface_water_temperature", selectedVariables)) {
        columns.push("lake_surface_water_temperature");
    }
    if (hasSelectedResultVariable("tsm", selectedVariables)) {
        columns.push("tsm");
    }
    var header = columns.map(function (column) {
        return "<th>" + column + "</th>";
    }).join("");

    header = header.replace("<th>lake_id</th>", "<th>Lake ID</th>");
    header = header.replace("<th>rainfall</th>", "<th>rainfall_mm</th>");
    header = header.replace("<th>burned_area</th>", "<th>burned_area_ha</th>");
    header = header.replace("<th>temperature</th>", "<th>temperature_c</th>");
    header = header.replace("<th>aod</th>", "<th>aod</th>");
    header = header.replace("<th>chla</th>", "<th>chla_mg_m3</th>");
    header = header.replace("<th>lake_surface_water_temperature</th>", "<th>lswt_c</th>");
    header = header.replace("<th>tsm</th>", "<th>tsm_g_m3</th>");

    var isDetailedTenDayView = isTenDayAggregation();

    var rows = data.map(function (row) {
        return "<tr>" + columns.map(function (column) {
            var rawValue = column === "lake_id" ? selectedLakeId : row[column];
            var value = rawValue;
            if (column === "land_cover") {
                value = getLandCoverLabel(value);
            } else if (column === "burned_area") {
                value = value === undefined || value === null || value === ""
                    ? "--"
                    : (isDetailedTenDayView ? formatBurnedAreaHectaresDetailed(value) : formatBurnedAreaHectares(value));
            } else if (column === "rainfall") {
                value = isDetailedTenDayView ? formatRainfallMillimetersDetailed(value) : formatRainfallMillimeters(value);
            } else if (column === "temperature") {
                value = isDetailedTenDayView ? formatTemperatureDetailed(value) : formatTemperatureCelsius(value);
            } else if (column === "aod") {
                value = isDetailedTenDayView ? formatAodDetailed(value) : formatAodValue(value);
            } else if (column === "chla") {
                value = isDetailedTenDayView ? formatChlaDetailed(value) : formatChlaValue(value);
            } else if (column === "lake_surface_water_temperature") {
                value = isDetailedTenDayView ? formatLswtDetailed(value) : formatLswtValue(value);
            } else if (column === "tsm") {
                value = isDetailedTenDayView ? formatTsmDetailed(value) : formatTsmValue(value);
            } else if (value === undefined || value === null || value === "") {
                value = "--";
            }
            return "<td>" + value + "</td>";
        }).join("") + "</tr>";
    }).join("");

    tableContainer.innerHTML =
        "<table><thead><tr>" + header + "</tr></thead><tbody>" + rows + "</tbody></table>";

    if (data.length) {
        var firstRenderedRow = tableContainer.querySelector("tbody tr");
        var domValuesByColumn = {};

        if (firstRenderedRow) {
            Array.prototype.slice.call(firstRenderedRow.children).forEach(function (cell, index) {
                domValuesByColumn[columns[index]] = cell.textContent;
            });
        }

        logTemporalDebug("table_dom_values", {
            selectedDate: startDateInput.value,
            effectiveRecordDate: data[0].date,
            aggregation: lastRequestedAggregation,
            apiValues: {
                burned_area: data[0].burned_area,
                rainfall: data[0].rainfall,
                temperature: data[0].temperature,
                aod: data[0].aod,
                chla: data[0].chla,
                lake_surface_water_temperature: data[0].lake_surface_water_temperature,
                tsm: data[0].tsm
            },
            renderTableRow: data[0],
            domValuesByColumn: domValuesByColumn
        });
    }
}

function getNumericValues(data, fieldName) {
    return data
        .map(function (row) {
            return Number(row[fieldName]);
        })
        .filter(function (value) {
            return !isNaN(value);
        });
}

function computeDescriptiveStats(values) {
    if (!values.length) {
        return null;
    }

    var sortedValues = values.slice().sort(function (left, right) {
        return left - right;
    });
    var count = sortedValues.length;
    var mean = sortedValues.reduce(function (sum, value) {
        return sum + value;
    }, 0) / count;
    var midpoint = Math.floor(count / 2);
    var median = count % 2 === 0
        ? (sortedValues[midpoint - 1] + sortedValues[midpoint]) / 2
        : sortedValues[midpoint];
    var variance = sortedValues.reduce(function (sum, value) {
        var delta = value - mean;
        return sum + delta * delta;
    }, 0) / count;

    return {
        mean: mean,
        median: median,
        stdDev: Math.sqrt(variance)
    };
}

function getCurrentLakeLayerMeanValue(variableKey) {
    var values = getNumericValues(currentResults, variableKey);
    var stats = computeDescriptiveStats(values);
    return stats ? stats.mean : null;
}

function getLakeLayerDisplayValue(variableKey, value) {
    return formatVariableValue(variableKey, value, true);
}

function getLakeLayerStyle(variableKey, value) {
    var config = getLakeCciLayerConfig(variableKey);
    if (!config || value === null || value === undefined || isNaN(Number(value))) {
        return {
            color: "#94a3b8",
            weight: 2,
            fillColor: "#cbd5e1",
            fillOpacity: 0.75
        };
    }

    var numericValue = Number(value);
    var magnitude = Math.abs(numericValue);
    var ratio = magnitude <= 1e-12 ? 0.5 : Math.max(0.12, Math.min(1, 0.35 + (magnitude / (magnitude + 1))));

    return {
        color: "#0f172a",
        weight: 2.2,
        fillColor: getInterpolatedRampColor(config.colors, ratio),
        fillOpacity: 0.78
    };
}

function getMetricSummaryConfig(useDetailedTenDayFormatting) {
    return [
        {
            key: "burned_area",
            field: "burned_area",
            label: "Burned Area (ha)",
            formatter: useDetailedTenDayFormatting ? formatBurnedAreaHectaresDetailed : formatBurnedAreaHectares,
            elements: {
                mean: avgBurnedArea,
                median: medianBurnedArea,
                std: stdBurnedArea
            }
        },
        {
            key: "rainfall",
            field: "rainfall",
            label: "Rainfall (mm)",
            formatter: useDetailedTenDayFormatting ? formatRainfallMillimetersDetailed : formatRainfallMillimeters,
            elements: {
                mean: avgRainfall,
                median: medianRainfall,
                std: stdRainfall
            }
        },
        {
            key: "temperature",
            field: "temperature",
            label: "Temperature (\u00B0C)",
            formatter: useDetailedTenDayFormatting ? formatTemperatureDetailed : formatTemperatureCelsius,
            elements: {
                mean: avgTemperature,
                median: medianTemperature,
                std: stdTemperature
            }
        },
        {
            key: "aod",
            field: "aod",
            label: "AOD",
            formatter: useDetailedTenDayFormatting ? formatAodDetailed : formatAodValue,
            elements: {
                mean: avgAod,
                median: medianAod,
                std: stdAod
            }
        },
        {
            key: "chla",
            field: "chla",
            label: "Chlorophyll-a (mg/m3)",
            formatter: useDetailedTenDayFormatting ? formatChlaDetailed : formatChlaValue,
            elements: {
                mean: avgChla,
                median: medianChla,
                std: stdChla
            }
        },
        {
            key: "lake_surface_water_temperature",
            field: "lake_surface_water_temperature",
            label: "LSWT (\u00B0C)",
            formatter: useDetailedTenDayFormatting ? formatLswtDetailed : formatLswtValue,
            elements: {
                mean: avgLswt,
                median: medianLswt,
                std: stdLswt
            }
        },
        {
            key: "tsm",
            field: "tsm",
            label: "Turbidity Proxy (g/m3)",
            formatter: useDetailedTenDayFormatting ? formatTsmDetailed : formatTsmValue,
            elements: {
                mean: avgTsm,
                median: medianTsm,
                std: stdTsm
            }
        }
    ];
}

function buildStatisticsSummaryRows(data, selectedVariables) {
    return getMetricSummaryConfig(isTenDayAggregation())
        .filter(function (config) {
            return hasSelectedResultVariable(config.key, selectedVariables);
        })
        .map(function (config) {
            var stats = computeDescriptiveStats(getNumericValues(data, config.field));
            return {
                variable: config.label,
                mean: stats ? config.formatter(stats.mean) : "--",
                median: stats ? config.formatter(stats.median) : "--",
                stdDev: stats ? config.formatter(stats.stdDev) : "--"
            };
        });
}

function setKpiStatisticTriplet(elements, stats, formatter, isVisible) {
    var fallbackValue = "--";
    var meanValue = isVisible && stats ? formatter(stats.mean) : fallbackValue;
    var medianValue = isVisible && stats ? formatter(stats.median) : fallbackValue;
    var stdValue = isVisible && stats ? formatter(stats.stdDev) : fallbackValue;

    elements.mean.textContent = meanValue;
    elements.median.textContent = medianValue;
    elements.std.textContent = stdValue;
}

function updateSummary(data, selectedVariables) {
    var metricConfig = getMetricSummaryConfig(isTenDayAggregation());

    metricConfig.forEach(function (config) {
        var stats = computeDescriptiveStats(getNumericValues(data, config.field));
        setKpiStatisticTriplet(
            config.elements,
            stats,
            config.formatter,
            data.length && hasSelectedResultVariable(config.key, selectedVariables)
        );
    });

    logTemporalDebug("kpi_input", {
        aggregation: lastRequestedAggregation,
        selectedDateStart: startDateInput.value,
        selectedDateEnd: endDateInput.value,
        recordCount: data.length,
        records: data
    });

    if (data.length) {
        logTemporalDebug("kpi_dom_values", {
            selectedDate: startDateInput.value,
            effectiveRecordDate: data[0].date,
            aggregation: lastRequestedAggregation,
            apiValues: {
                burned_area: data[0].burned_area,
                rainfall: data[0].rainfall,
                temperature: data[0].temperature,
                aod: data[0].aod,
                chla: data[0].chla,
                lake_surface_water_temperature: data[0].lake_surface_water_temperature,
                tsm: data[0].tsm
            },
            displayedValues: {
                burned_area_mean: avgBurnedArea ? avgBurnedArea.textContent : null,
                rainfall_mean: avgRainfall ? avgRainfall.textContent : null,
                temperature_mean: avgTemperature ? avgTemperature.textContent : null,
                aod_mean: avgAod ? avgAod.textContent : null,
                chla_mean: avgChla ? avgChla.textContent : null,
                lswt_mean: avgLswt ? avgLswt.textContent : null,
                tsm_mean: avgTsm ? avgTsm.textContent : null,
                burned_area_median: medianBurnedArea ? medianBurnedArea.textContent : null,
                rainfall_median: medianRainfall ? medianRainfall.textContent : null,
                temperature_median: medianTemperature ? medianTemperature.textContent : null,
                aod_median: medianAod ? medianAod.textContent : null,
                chla_median: medianChla ? medianChla.textContent : null,
                lswt_median: medianLswt ? medianLswt.textContent : null,
                tsm_median: medianTsm ? medianTsm.textContent : null
            },
            preciseBurnedAreaDisplay: formatBurnedAreaHectaresPrecise(data[0].burned_area)
        });
    }

    if (!data.length) {
        dominantLandCover.textContent = "--";
        return;
    }

    var landCoverCounts = {};

    data.forEach(function (row) {
        var landCoverValue = getLandCoverValue(row.land_cover);
        if (landCoverValue === null) {
            return;
        }
        landCoverCounts[landCoverValue] = (landCoverCounts[landCoverValue] || 0) + 1;
    });

    var dominantLandCoverId = Object.keys(landCoverCounts).reduce(function (bestId, currentId) {
        if (!bestId || landCoverCounts[currentId] > landCoverCounts[bestId]) {
            return currentId;
        }
        return bestId;
    }, null);

    dominantLandCover.textContent = dominantLandCoverId
        ? getLandCoverLabel(dominantLandCoverId)
        : "N/A";
}

function renderStatisticsSummaryTable(data, selectedVariables) {
    if (!statisticsTableContainer) {
        return;
    }

    if (!data.length) {
        statisticsTableContainer.innerHTML = '<p class="placeholder">Statistics summary will appear here.</p>';
        return;
    }

    var summaryRows = buildStatisticsSummaryRows(data, selectedVariables);

    if (!summaryRows.length) {
        statisticsTableContainer.innerHTML = '<p class="placeholder">No variable statistics available for the current selection.</p>';
        return;
    }

    var rows = summaryRows.map(function (row) {
        return "<tr>" +
            "<td>" + row.variable + "</td>" +
            "<td>" + row.mean + "</td>" +
            "<td>" + row.median + "</td>" +
            "<td>" + row.stdDev + "</td>" +
            "</tr>";
    }).join("");

    statisticsTableContainer.innerHTML =
        "<table><thead><tr>" +
        "<th>Variable</th>" +
        "<th>Mean</th>" +
        "<th>Median</th>" +
        "<th>Standard Deviation</th>" +
        "</tr></thead><tbody>" + rows + "</tbody></table>";
}

function updateLakeSummary(summary) {
    if (!lakeCoverage || !waterInsight) {
        return;
    }

    if (!summary) {
        lakeCoverage.textContent = "--";
        waterInsight.textContent = "Lake-based insight will appear here after analysis.";
        return;
    }

    lakeCoverage.textContent = typeof summary.lake_coverage_percent === "number"
        ? summary.lake_coverage_percent.toFixed(2) + "%"
        : "--";

    waterInsight.textContent = summary.water_insight || "Lake-based insight unavailable.";
}

function renderChart(data, selectedVariables) {
    var ctx = resultsChartCanvas.getContext("2d");
    var labels = data.map(function (row) {
        return row.date;
    });

    var burnedArea = data.map(function (row) {
        var hectaresValue = squareMetersToHectares(row.burned_area);
        return hectaresValue === null ? null : hectaresValue;
    });

    var rainfall = data.map(function (row) {
        var rainfallMillimeters = metersToMillimeters(row.rainfall);
        return rainfallMillimeters === null ? 0 : rainfallMillimeters;
    });

    var temperature = data.map(function (row) {
        var numericValue = Number(row.temperature);
        return isNaN(numericValue) ? null : numericValue;
    });

    var aod = data.map(function (row) {
        var numericValue = Number(row.aod);
        return isNaN(numericValue) ? null : numericValue;
    });

    var chla = data.map(function (row) {
        var numericValue = Number(row.chla);
        return isNaN(numericValue) ? null : numericValue;
    });

    var lswt = data.map(function (row) {
        var numericValue = Number(row.lake_surface_water_temperature);
        return isNaN(numericValue) ? null : numericValue;
    });

    var tsm = data.map(function (row) {
        var numericValue = Number(row.tsm);
        return isNaN(numericValue) ? null : numericValue;
    });

    logTemporalDebug("chart_input", {
        aggregation: lastRequestedAggregation,
        selectedDateStart: startDateInput.value,
        selectedDateEnd: endDateInput.value,
        labels: labels,
        burnedArea: burnedArea,
        rainfall: rainfall,
        temperature: temperature,
        aod: aod,
        chla: chla,
        lswt: lswt,
        tsm: tsm
    });

    if (resultsChart) {
        resultsChart.destroy();
    }

    var datasets = [];
    var scales = {
        x: {
            grid: {
                color: chartGridColor
            },
            ticks: {
                color: chartTextColor,
                maxRotation: 0,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        }
    };

    if (hasSelectedResultVariable("burned_area", selectedVariables)) {
        datasets.push({
            label: "Burned Area (ha)",
            data: burnedArea,
            borderColor: "#f97316",
            backgroundColor: "rgba(249, 115, 22, 0.12)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y"
        });
        scales.y = {
            position: "left",
            grid: {
                color: chartGridColor
            },
            title: {
                display: true,
                text: "Burned Area (ha)",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    if (hasSelectedResultVariable("rainfall", selectedVariables)) {
        datasets.push({
            label: "Rainfall (mm)",
            data: rainfall,
            borderColor: "#10b981",
            backgroundColor: "rgba(16, 185, 129, 0.12)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y1"
        });
        scales.y1 = {
            position: "right",
            grid: {
                drawOnChartArea: false
            },
            title: {
                display: true,
                text: "Rainfall (mm)",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    if (hasSelectedResultVariable("temperature", selectedVariables)) {
        datasets.push({
            label: "Temperature (\u00B0C)",
            data: temperature,
            borderColor: "#ef4444",
            backgroundColor: "rgba(239, 68, 68, 0.14)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y2"
        });
        scales.y2 = {
            position: "right",
            offset: true,
            grid: {
                drawOnChartArea: false
            },
            title: {
                display: true,
                text: "Temperature (\u00B0C)",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    if (hasSelectedResultVariable("aod", selectedVariables)) {
        datasets.push({
            label: "AOD",
            data: aod,
            borderColor: "#8b5cf6",
            backgroundColor: "rgba(139, 92, 246, 0.12)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y3"
        });
        scales.y3 = {
            position: "right",
            offset: true,
            grid: {
                drawOnChartArea: false
            },
            title: {
                display: true,
                text: "AOD",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    if (hasSelectedResultVariable("chla", selectedVariables)) {
        datasets.push({
            label: "Chlorophyll-a (mg/m3)",
            data: chla,
            borderColor: "#0f766e",
            backgroundColor: "rgba(15, 118, 110, 0.12)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y4"
        });
        scales.y4 = {
            position: "left",
            offset: true,
            grid: {
                drawOnChartArea: false
            },
            title: {
                display: true,
                text: "Chlorophyll-a (mg/m3)",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    if (hasSelectedResultVariable("lake_surface_water_temperature", selectedVariables)) {
        datasets.push({
            label: "LSWT (\u00B0C)",
            data: lswt,
            borderColor: "#dc2626",
            backgroundColor: "rgba(220, 38, 38, 0.12)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y5"
        });
        scales.y5 = {
            position: "right",
            offset: true,
            grid: {
                drawOnChartArea: false
            },
            title: {
                display: true,
                text: "LSWT (\u00B0C)",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    if (hasSelectedResultVariable("tsm", selectedVariables)) {
        datasets.push({
            label: "Turbidity Proxy (g/m3)",
            data: tsm,
            borderColor: "#7c3aed",
            backgroundColor: "rgba(124, 58, 237, 0.12)",
            borderWidth: 3,
            pointRadius: 2,
            pointHoverRadius: 5,
            tension: 0.35,
            yAxisID: "y6"
        });
        scales.y6 = {
            position: "left",
            offset: true,
            grid: {
                drawOnChartArea: false
            },
            title: {
                display: true,
                text: "Turbidity Proxy (g/m3)",
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 700
                }
            },
            ticks: {
                color: chartTextColor,
                font: {
                    family: chartFontFamily,
                    size: 11,
                    weight: 600
                }
            }
        };
    }

    resultsChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 450
            },
            interaction: {
                mode: "index",
                intersect: false
            },
            scales: scales,
            plugins: {
                legend: {
                    labels: {
                        color: chartTextColor,
                        usePointStyle: true,
                        boxWidth: 10,
                        padding: 14,
                        font: {
                            family: chartFontFamily,
                            size: 11,
                            weight: 700
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            return formatChartTooltipValue(context.dataset.label || "Value", context.parsed.y);
                        }
                    }
                }
            }
        }
    });
}

function removeBurnedAreaOverlay() {
    if (burnedAreaOverlay) {
        map.removeLayer(burnedAreaOverlay);
        burnedAreaOverlay = null;
    }

    if (burnedAreaLegend) {
        map.removeControl(burnedAreaLegend);
        burnedAreaLegend = null;
    }
}

function removeTemperatureOverlay() {
    if (temperatureOverlay) {
        map.removeLayer(temperatureOverlay);
        temperatureOverlay = null;
    }

    if (temperatureLegend) {
        map.removeControl(temperatureLegend);
        temperatureLegend = null;
    }
}

function removeAodOverlay() {
    if (aodOverlay) {
        map.removeLayer(aodOverlay);
        aodOverlay = null;
    }

    if (aodLegend) {
        map.removeControl(aodLegend);
        aodLegend = null;
    }
}

function removeChlaLayer() {
    if (chlaLayer) {
        map.removeLayer(chlaLayer);
        chlaLayer = null;
    }

    if (chlaLegend) {
        map.removeControl(chlaLegend);
        chlaLegend = null;
    }
}

function removeLswtLayer() {
    if (lswtLayer) {
        map.removeLayer(lswtLayer);
        lswtLayer = null;
    }

    if (lswtLegend) {
        map.removeControl(lswtLegend);
        lswtLegend = null;
    }
}

function removeTsmLayer() {
    if (tsmLayer) {
        map.removeLayer(tsmLayer);
        tsmLayer = null;
    }

    if (tsmLegend) {
        map.removeControl(tsmLegend);
        tsmLegend = null;
    }
}

function removeLandcoverLegend() {
    if (landcoverLegend) {
        map.removeControl(landcoverLegend);
        landcoverLegend = null;
    }
}

function getAvailableLandCoverEntries() {
    var availableValues = {};

    currentResults.forEach(function (row) {
        var landCoverValue = getLandCoverValue(row.land_cover);
        if (landCoverValue === null || !landCoverMap[landCoverValue] || !landCoverColors[landCoverValue]) {
            return;
        }

        availableValues[landCoverValue] = true;
    });

    return Object.keys(availableValues)
        .map(function (value) {
            var numericValue = Number(value);
            return {
                value: numericValue,
                label: landCoverMap[numericValue],
                color: landCoverColors[numericValue]
            };
        })
        .sort(function (a, b) {
            return a.value - b.value;
        });
}

function addLandcoverLegend() {
    removeLandcoverLegend();

    if (!hasCompletedAnalysis || !selectedCatchmentLayer) {
        return;
    }

    var entries = getAvailableLandCoverEntries();
    if (!entries.length) {
        return;
    }

    landcoverLegend = L.control({ position: "bottomright" });

    landcoverLegend.onAdd = function () {
        var div = L.DomUtil.create("div", "legend landcover-legend");
        var itemsMarkup = entries.map(function (entry) {
            return (
                '<div class="landcover-legend-item">' +
                    '<span class="landcover-legend-swatch" style="background:' + entry.color + ';"></span>' +
                    '<span class="landcover-legend-label">' + entry.label + "</span>" +
                "</div>"
            );
        }).join("");

        div.innerHTML =
            '<div class="landcover-legend-title">Land Cover</div>' +
            '<div class="landcover-legend-items">' + itemsMarkup + "</div>";
        return div;
    };

    landcoverLegend.addTo(map);
    window.setTimeout(function () {
        var element = landcoverLegend && landcoverLegend.getContainer ? landcoverLegend.getContainer() : null;
        if (element) {
            element.classList.add("is-visible");
        }
    }, 20);
}

function syncLandcoverLegend() {
    addLandcoverLegend();
}

function removeLakesLayer() {
    if (lakesLayer) {
        map.removeLayer(lakesLayer);
        lakesLayer = null;
    }
}

function removeSelectedLakeHighlightLayer() {
    if (selectedLakeHighlightLayer) {
        map.removeLayer(selectedLakeHighlightLayer);
        selectedLakeHighlightLayer = null;
    }
}

function syncSelectedLakeHighlightLayer() {
    removeSelectedLakeHighlightLayer();

    if (!selectedLakeFeature || !selectedLakeId) {
        return;
    }

    selectedLakeHighlightLayer = L.geoJSON(selectedLakeFeature, {
        pane: "selectedLakePane",
        style: function () {
            return {
                color: "#0f4c81",
                weight: 2.8,
                fillColor: "#1E90FF",
                fillOpacity: 0.08
            };
        },
        interactive: false
    }).addTo(map);
}

function syncLakesLayer() {
    removeLakesLayer();

    if (!lakesGeoJsonData || !lakesLayerToggle || !lakesLayerToggle.checked || !hasCompletedAnalysis) {
        return;
    }

    if (!Array.isArray(lakesGeoJsonData.features) || !lakesGeoJsonData.features.length) {
        return;
    }

    lakesLayer = L.geoJSON(lakesGeoJsonData, {
        pane: "lakesPane",
        style: function () {
            return {
                color: "#1E90FF",
                fillColor: "#1E90FF",
                fillOpacity: 0.5,
                weight: 1
            };
        }
    }).addTo(map);
}

function resetLakeOverviewStyle(layer) {
    var featureLakeId = layer && layer.feature && layer.feature.properties
        ? String(layer.feature.properties.Lake_ID)
        : null;
    layer.setStyle(featureLakeId === String(selectedLakeId) ? getSelectedLakeStyle() : getLakeStyle());
}

function updateLakeOverviewSelection() {
    if (!lakesOverviewLayer) {
        return;
    }

    lakesOverviewLayer.eachLayer(function (layer) {
        resetLakeOverviewStyle(layer);
    });
}

function applyLakeSelection(selectionPayload) {
    selectedLakeId = selectionPayload && selectionPayload.lake_id ? String(selectionPayload.lake_id) : null;
    selectedLakeCatchmentId = selectionPayload && selectionPayload.catchment_id ? String(selectionPayload.catchment_id) : null;
    selectedLakeLabel = selectionPayload && selectionPayload.lake_label ? selectionPayload.lake_label : null;
    selectedLakeFeature = selectionPayload && selectionPayload.lake ? selectionPayload.lake : null;

    setSelectedLakeDisplay(selectedLakeLabel);
    updateRunButtonState();
    updateLakeOverviewSelection();
    syncSelectedLakeHighlightLayer();

    if (!selectedLakeCatchmentId) {
        catchmentSelect.innerHTML = '<option value="">No matching catchment</option>';
        removeSelectedCatchmentLayer();
        setStatus("This lake does not map to a catchment in the current dataset.", true);
        return;
    }

    catchmentSelect.innerHTML = '<option value="' + selectedLakeCatchmentId + '">' + selectedLakeCatchmentId + "</option>";
    catchmentSelect.value = selectedLakeCatchmentId;

    var cachedCatchmentFeature = findCatchmentFeatureById(selectedLakeCatchmentId);
    if (cachedCatchmentFeature) {
        showSelectedCatchment(cachedCatchmentFeature, true);
    } else if (selectionPayload.catchment) {
        showSelectedCatchment(selectionPayload.catchment, true);
    }

    updateQuickStats(null);
    setStatus("Lake selected. Choose dates and run analysis.", false);
}

function handleLakeSelection(lakeId) {
    fetch(buildApiUrl("/lake-selection?lake_id=" + encodeURIComponent(lakeId)))
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Failed to map lake to catchment");
            }
            return response.json();
        })
        .then(function (payload) {
            resetResults();
            applyLakeSelection(payload);
        })
        .catch(function (error) {
            console.error(error);
            setStatus("Could not map the selected lake to a catchment.", true);
        });
}

function loadLakesOverview() {
    return fetch(buildApiUrl("/lakes-overview"))
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Failed to fetch lakes overview");
            }
            return response.json();
        })
        .then(function (data) {
            if (!data.features || !data.features.length) {
                throw new Error("No lakes available for selection");
            }

            lakesOverviewLayer = L.geoJSON(data, {
                pane: "lakesPane",
                style: function () {
                    return getLakeStyle();
                },
                onEachFeature: function (feature, layer) {
                    var lakeId = feature.properties && feature.properties.Lake_ID !== undefined
                        ? String(feature.properties.Lake_ID)
                        : null;

                    if (lakeId) {
                        layer.bindTooltip("Lake " + lakeId, {
                            direction: "top",
                            sticky: true,
                            className: "catchment-tooltip",
                            opacity: 1
                        });
                    }

                    layer.on("mouseover", function () {
                        if (String(lakeId) !== String(selectedLakeId)) {
                            layer.setStyle(getLakeHoverStyle());
                        }
                        if (layer._path) {
                            layer._path.style.cursor = "pointer";
                        }
                    });

                    layer.on("mouseout", function () {
                        resetLakeOverviewStyle(layer);
                    });

                    layer.on("click", function () {
                        if (!lakeId) {
                            setStatus("This lake is missing an ID.", true);
                            return;
                        }

                        handleLakeSelection(lakeId);
                    });
                }
            }).addTo(map);

            if (!hasAoiMapView) {
                map.fitBounds(lakesOverviewLayer.getBounds(), {
                    paddingTopLeft: [24, 80],
                    paddingBottomRight: [24, 24]
                });
            }
            setStatus("Lakes loaded. Select a lake on the map to begin.", false);
        });
}

function addBurnedAreaLegend(legendConfig) {
    if (!legendConfig || legendConfig.has_data === false) {
        return;
    }

    burnedAreaLegend = addGradientLegendControl(
        legendConfig,
        {
            position: "bottomright",
            title: "Burned Area Intensity",
            unit: null,
            min_label: "Low",
            max_label: "High",
            colors: ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]
        }
    );
}

function addTemperatureLegend(legendConfig) {
    if (!legendConfig || legendConfig.has_data === false) {
        return;
    }

    var normalizedLegendConfig = Object.assign({}, legendConfig, {
        position: "bottomright",
        title: "Temperature",
        unit: "\u00B0C"
    });

    temperatureLegend = addGradientLegendControl(
        normalizedLegendConfig,
        {
            position: "bottomright",
            title: "Temperature",
            unit: "\u00B0C",
            min_label: "Cold",
            max_label: "Hot",
            colors: ["#313695", "#4575b4", "#74add1", "#fee090", "#f46d43", "#a50026"],
            extraClassName: "temperature-legend"
        }
    );
}

function addAodLegend(legendConfig) {
    if (!legendConfig || legendConfig.has_data === false) {
        return;
    }

    if (aodLegend) {
        map.removeControl(aodLegend);
        aodLegend = null;
    }

    var normalizedLegendConfig = Object.assign({}, legendConfig, {
        position: "bottomright",
        title: "AOD Concentration",
        unit: null,
        min_label: "Low",
        max_label: "High",
        colors: ["#3182bd", "#41b6c4", "#7fcdbb", "#ffffb3", "#fdae61", "#d7191c"]
    });

    aodLegend = addGradientLegendControl(
        normalizedLegendConfig,
        {
            position: "bottomright",
            title: "AOD Concentration",
            unit: null,
            min_label: "Low",
            max_label: "High",
            colors: ["#3182bd", "#41b6c4", "#7fcdbb", "#ffffb3", "#fdae61", "#d7191c"]
        }
    );
}

function addLakeCciLegend(variableKey) {
    var config = getLakeCciLayerConfig(variableKey);
    if (!config) {
        return null;
    }

    return addGradientLegendControl(
        {
            position: "bottomright",
            title: config.title,
            unit: config.unit,
            min_label: config.minLabel,
            max_label: config.maxLabel,
            colors: config.colors
        },
        {
            position: "bottomright",
            title: config.title,
            unit: config.unit,
            min_label: config.minLabel,
            max_label: config.maxLabel,
            colors: config.colors
        }
    );
}

function addGradientLegendControl(legendConfig, defaults) {
    var resolvedConfig = Object.assign({}, defaults || {}, legendConfig || {});
    var control = L.control({ position: resolvedConfig.position || "bottomright" });

    control.onAdd = function () {
        var classNames = ["legend", "burned-legend"];
        if (resolvedConfig.extraClassName) {
            classNames.push(resolvedConfig.extraClassName);
        }

        var div = L.DomUtil.create("div", classNames.join(" "));
        var colors = Array.isArray(resolvedConfig.colors) && resolvedConfig.colors.length
            ? resolvedConfig.colors
            : (defaults && defaults.colors) || [];
        var unitMarkup = resolvedConfig.unit
            ? '<div class="burned-legend-unit">' + resolvedConfig.unit + "</div>"
            : "";

        div.innerHTML =
            '<div class="burned-legend-title">' + (resolvedConfig.title || "") + "</div>" +
            unitMarkup +
            '<div class="burned-legend-scale" style="background:linear-gradient(90deg, ' + colors.join(", ") + ');"></div>' +
            '<div class="burned-legend-labels"><span>' +
            (resolvedConfig.min_label || "") +
            "</span><span>" +
            (resolvedConfig.max_label || "") +
            "</span></div>";
        return div;
    };

    control.addTo(map);
    window.setTimeout(function () {
        var element = control && control.getContainer ? control.getContainer() : null;
        if (element) {
            element.classList.add("is-visible");
        }
    }, 20);

    return control;
}

function syncBurnedAreaOverlay() {
    removeBurnedAreaOverlay();

    if (!hasSelectedResultVariable("burned_area")) {
        return;
    }

    if (!burnedAreaOverlayData || !burnedOverlayToggle || !burnedOverlayToggle.checked || !hasCompletedAnalysis) {
        return;
    }

    if (!burnedAreaOverlayData.image_url || !burnedAreaOverlayData.bounds) {
        return;
    }

    burnedAreaOverlay = L.imageOverlay(
        burnedAreaOverlayData.image_url,
        burnedAreaOverlayData.bounds,
        {
            pane: "burnedPane",
            opacity: 0,
            interactive: false,
            crossOrigin: true,
            className: "burned-area-overlay"
        }
    );

    burnedAreaOverlay.once("load", function () {
        burnedAreaOverlay.setOpacity(burnedAreaOverlayData.opacity || 0.8);
    });

    burnedAreaOverlay.addTo(map);
    if (burnedAreaOverlayData.has_burned_data && burnedAreaOverlayData.legend) {
        var legendConfig = Object.assign({}, burnedAreaOverlayData.legend, {
            has_data: burnedAreaOverlayData.has_burned_data
        });
        addBurnedAreaLegend(legendConfig);
    }
}

function syncTemperatureOverlay() {
    // Temperature uses its own overlay state so it can be toggled independently.
    removeTemperatureOverlay();

    if (!hasSelectedResultVariable("temperature")) {
        return;
    }

    if (!temperatureOverlayData || !temperatureOverlayToggle || !temperatureOverlayToggle.checked || !hasCompletedAnalysis) {
        return;
    }

    if (!temperatureOverlayData.image_url || !temperatureOverlayData.bounds) {
        return;
    }

    temperatureOverlay = L.imageOverlay(
        temperatureOverlayData.image_url,
        temperatureOverlayData.bounds,
        {
            pane: "temperaturePane",
            opacity: 0,
            interactive: false,
            crossOrigin: true,
            className: "burned-area-overlay"
        }
    );

    temperatureOverlay.once("load", function () {
        temperatureOverlay.setOpacity(temperatureOverlayData.opacity || 0.66);
    });

    temperatureOverlay.addTo(map);
    if (temperatureOverlayData.has_temperature_data && temperatureOverlayData.legend) {
        var legendConfig = Object.assign({}, temperatureOverlayData.legend, {
            has_data: temperatureOverlayData.has_temperature_data
        });
        addTemperatureLegend(legendConfig);
    }
}

function syncAodOverlay() {
    removeAodOverlay();

    if (!hasSelectedResultVariable("aod")) {
        return;
    }

    if (!aodOverlayData || !aodOverlayToggle || !aodOverlayToggle.checked || !hasCompletedAnalysis) {
        return;
    }

    if (!aodOverlayData.image_url || !aodOverlayData.bounds) {
        return;
    }

    aodOverlay = L.imageOverlay(
        aodOverlayData.image_url,
        aodOverlayData.bounds,
        {
            pane: "aodPane",
            opacity: 0,
            interactive: false,
            crossOrigin: true,
            className: "burned-area-overlay"
        }
    );

    aodOverlay.once("load", function () {
        aodOverlay.setOpacity(aodOverlayData.opacity || 0.62);
    });

    aodOverlay.addTo(map);
    if (aodOverlayData.has_aod_data && aodOverlayData.legend) {
        var legendConfig = Object.assign({}, aodOverlayData.legend, {
            has_data: aodOverlayData.has_aod_data
        });
        addAodLegend(legendConfig);
    }
}

function syncLakeIndicatorLayer(variableKey) {
    var removeLayerFn;
    var toggle;
    var overlayData = null;
    var paneName;
    if (variableKey === "chla") {
        removeLayerFn = removeChlaLayer;
        toggle = chlaLayerToggle;
        overlayData = chlaOverlayData;
        paneName = "lakeCciChlaPane";
    } else if (variableKey === "lake_surface_water_temperature") {
        removeLayerFn = removeLswtLayer;
        toggle = lswtLayerToggle;
        overlayData = lswtOverlayData;
        paneName = "lakeCciLswtPane";
    } else if (variableKey === "tsm") {
        removeLayerFn = removeTsmLayer;
        toggle = tsmLayerToggle;
        overlayData = tsmOverlayData;
        paneName = "lakeCciTsmPane";
    } else {
        return;
    }

    removeLayerFn();

    if (!hasSelectedResultVariable(variableKey)) {
        return;
    }

    if (!overlayData || !toggle || !toggle.checked || !hasCompletedAnalysis) {
        return;
    }

    if (!overlayData.image_url || !overlayData.bounds) {
        return;
    }

    var overlayLayer = L.imageOverlay(
        overlayData.image_url,
        overlayData.bounds,
        {
            pane: paneName,
            opacity: 0,
            interactive: false,
            crossOrigin: true,
            className: "burned-area-overlay"
        }
    );

    overlayLayer.once("load", function () {
        overlayLayer.setOpacity(overlayData.opacity || 0.82);
    });

    overlayLayer.addTo(map);

    if (variableKey === "chla") {
        chlaLayer = overlayLayer;
        chlaLegend = overlayData.legend && overlayData.has_data ? addLakeCciLegend(variableKey) : null;
    } else if (variableKey === "lake_surface_water_temperature") {
        lswtLayer = overlayLayer;
        lswtLegend = overlayData.legend && overlayData.has_data ? addLakeCciLegend(variableKey) : null;
    } else if (variableKey === "tsm") {
        tsmLayer = overlayLayer;
        tsmLegend = overlayData.legend && overlayData.has_data ? addLakeCciLegend(variableKey) : null;
    }
}

function resetResults(shouldInvalidateRequest) {
    if (shouldInvalidateRequest !== false) {
        currentRequestId += 1;
    }

    currentResults = [];
    hasCompletedAnalysis = false;
    burnedAreaOverlayData = null;
    temperatureOverlayData = null;
    aodOverlayData = null;
    chlaOverlayData = null;
    lswtOverlayData = null;
    tsmOverlayData = null;
    lakesGeoJsonData = null;
    removeBurnedAreaOverlay();
    removeTemperatureOverlay();
    removeAodOverlay();
    removeChlaLayer();
    removeLswtLayer();
    removeTsmLayer();
    removeSelectedLakeHighlightLayer();
    removeLandcoverLegend();
    removeLakesLayer();
    tableContainer.innerHTML = '<p class="placeholder">Results will appear here.</p>';
    if (statisticsTableContainer) {
        statisticsTableContainer.innerHTML = '<p class="placeholder">Statistics summary will appear here.</p>';
    }
    updateSummary([], getSelectedResultVariables());
    updateLakeSummary(null);
    updateResultsPeriodSummary([]);

    if (resultsChart) {
        resultsChart.destroy();
        resultsChart = null;
    }

    exportButton.disabled = true;
    setResetButtonVisible(false);
    updateQuickStats(null);
    setResultsPanelOpen(false);
    applySelectedResultVariableView({
        hasResults: false,
        syncOverlays: false
    });
}

function renderResults(data, overlay, temperatureOverlayPayload, aodOverlayPayload, chlaOverlayPayload, lswtOverlayPayload, tsmOverlayPayload, lakesData, summary, requestedVariables) {
    currentResults = data.slice();
    hasCompletedAnalysis = true;
    burnedAreaOverlayData = overlay || null;
    temperatureOverlayData = temperatureOverlayPayload || null;
    aodOverlayData = aodOverlayPayload || null;
    chlaOverlayData = chlaOverlayPayload || null;
    lswtOverlayData = lswtOverlayPayload || null;
    tsmOverlayData = tsmOverlayPayload || null;
    lakesGeoJsonData = lakesData || null;
    lastRequestedVariables = requestedVariables && requestedVariables.length
        ? requestedVariables.slice()
        : getSelectedResultVariables();

    logTemporalDebug("api_response", {
        aggregation: lastRequestedAggregation,
        selectedDateStart: startDateInput.value,
        selectedDateEnd: endDateInput.value,
        recordCount: data.length,
        dates: data.map(function (row) { return row.date; }),
        records: data
    });
    updateResultsPeriodSummary(data);

    setResetButtonVisible(true);
    syncLakesLayer();
    syncLandcoverLegend();
    animateResultsShell();
    logLandCoverValues(data);
    updateLakeSummary(summary || null);
    applySelectedResultVariableView({
        hasResults: true,
        syncOverlays: true
    });
    updateQuickStats(data.length);
    setResultsPanelOpen(true);
}

function resetAnalysisUiState() {
    resetResults();

    if (selectedLakeCatchmentId && startDateInput.value && endDateInput.value) {
        highlightCatchment(selectedLakeCatchmentId);
        setStatus("Analysis reset. Run analysis to load a new burned-area overlay.", false);
        return;
    }

    if (selectedLakeCatchmentId) {
        highlightCatchment(selectedLakeCatchmentId);
        setStatus("Analysis reset. Choose dates and run analysis again.", false);
        return;
    }

    activeCatchmentId = null;
    removeSelectedCatchmentLayer();
    setStatus("Select a lake on the map to begin.", false);
}

function exportResultsAsCsv() {
    if (!currentResults.length) {
        setStatus("No results available to export yet.", true);
        return;
    }

    var selectedVariables = getSelectedResultVariables();
    var selectedLakeIdentifier = selectedLakeId || "";
    var aggregationLevel = lastRequestedAggregation || getSelectedAggregationMode();
    var statisticsSummaryRows = buildStatisticsSummaryRows(currentResults, selectedVariables);
    var exportRows = currentResults.map(function (row) {
        var formattedRow = {
            lake_id: selectedLakeIdentifier,
            catchment_id: row.catchment_id,
            date: row.date,
            aggregation_level: aggregationLevel
        };

        if (hasSelectedResultVariable("burned_area", selectedVariables)) {
            formattedRow.burned_area_ha = squareMetersToHectares(row.burned_area);
        }

        if (hasSelectedResultVariable("rainfall", selectedVariables)) {
            formattedRow.rainfall = row.rainfall;
        }

        if (hasSelectedResultVariable("temperature", selectedVariables)) {
            formattedRow.temperature = row.temperature;
        }

        if (hasSelectedResultVariable("aod", selectedVariables)) {
            formattedRow.aod = row.aod;
        }

        if (hasSelectedResultVariable("chla", selectedVariables)) {
            formattedRow.chla = row.chla;
        }

        if (hasSelectedResultVariable("lake_surface_water_temperature", selectedVariables)) {
            formattedRow.lake_surface_water_temperature = row.lake_surface_water_temperature;
        }

        if (hasSelectedResultVariable("tsm", selectedVariables)) {
            formattedRow.tsm = row.tsm;
        }
        return formattedRow;
    });

    logTemporalDebug("csv_export", {
        aggregation: aggregationLevel,
        selectedDateStart: startDateInput.value,
        selectedDateEnd: endDateInput.value,
        recordCount: exportRows.length,
        records: exportRows
    });

    var columns = Object.keys(exportRows[0]);
    var csvLines = [
        columns.join(",")
    ];

    exportRows.forEach(function (row) {
        var values = columns.map(function (column) {
            var value = row[column] === undefined || row[column] === null ? "" : String(row[column]);
            return '"' + value.replace(/"/g, '""') + '"';
        });
        csvLines.push(values.join(","));
    });

    if (statisticsSummaryRows.length) {
        csvLines.push("");
        csvLines.push("Statistics Summary");
        csvLines.push(["Variable", "Mean", "Median", "Standard Deviation"].join(","));
        statisticsSummaryRows.forEach(function (row) {
            csvLines.push([
                row.variable,
                row.mean,
                row.median,
                row.stdDev
            ].map(function (value) {
                return '"' + String(value).replace(/"/g, '""') + '"';
            }).join(","));
        });
    }

    var blob = new Blob([csvLines.join("\n")], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "analysis_results.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

function addLandcoverOverlay() {
    var bounds = [[15, -170], [75, -50]];
    landcoverOverlay = L.imageOverlay("data/landcover.png", bounds, {
        opacity: 0.18
    });
    landcoverOverlay.addTo(map);
}

function loadLandCoverLookup() {
    return fetch(buildApiUrl("/land-cover"))
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Failed to fetch land cover lookup");
            }
            return response.json();
        })
        .then(function (lookup) {
            landCoverByCatchment = lookup || {};
        })
        .catch(function (error) {
            console.warn("Land cover lookup unavailable:", error);
            landCoverByCatchment = {};
        });
}

function loadCatchmentIdMap() {
    return fetch("data/catchment-id-map.json")
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Failed to fetch catchment ID map");
            }
            return response.json();
        })
        .then(function (lookup) {
            catchmentIdByOutlet = lookup || {};
        })
        .catch(function (error) {
            console.error("Catchment ID map unavailable:", error);
            catchmentIdByOutlet = {};
            throw error;
        });
}

function loadAoiBounds() {
    return fetch("data/catchments_aoi.geojson")
        .then(function (response) {
            if (!response.ok) {
                throw new Error("Failed to fetch AOI");
            }
            return response.json();
        })
        .then(function (data) {
            var aoiLayer = L.geoJSON(data);
            var bounds = aoiLayer.getBounds();

            if (bounds.isValid()) {
                map.fitBounds(bounds, {
                    paddingTopLeft: [24, 80],
                    paddingBottomRight: [24, 24]
                });
                hasAoiMapView = true;
            }
        })
        .catch(function (error) {
            console.warn("AOI unavailable:", error);
        });
}

function loadCatchmentsGeoJSON() {
    Promise.all([
        fetch("data/catchments_aoi.geojson")
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Failed to fetch GeoJSON");
                }
                return response.text();
            }),
        loadLandCoverLookup(),
        loadCatchmentIdMap()
    ])
        .then(function (results) {
            var text = results[0];

            if (!text || text.length < 10) {
                throw new Error("GeoJSON file is empty or invalid");
            }

            var data;
            try {
                data = JSON.parse(text);
            } catch (e) {
                throw new Error("Invalid JSON format");
            }

            if (!data.features || data.features.length === 0) {
                throw new Error("No features found in GeoJSON");
            }

            data.features.forEach(function (feature) {
                var outletId = feature.properties.Outlet_id;
                var catchmentId = outletId !== undefined && outletId !== null
                    ? catchmentIdByOutlet[String(outletId)]
                    : null;

                feature.properties.catchment_id = catchmentId || null;
                feature.properties.land_cover = catchmentId ? landCoverByCatchment[String(catchmentId)] : undefined;
            });

            catchmentsGeoJsonData = data;
            catchmentSelect.innerHTML = '<option value="">Select a lake on the map</option>';
            resetResults();
            updateQuickStats(null);
        })
        .catch(function (error) {
            console.error("GeoJSON ERROR:", error);
            catchmentSelect.innerHTML = '<option value="">GeoJSON error</option>';
            setStatus(error.message, true);
        });
}

function handleFilterChange() {
    if (!selectedLakeId) {
        setStatus("Select a lake on the map to begin.", false);
        return;
    }
}

function handleDateChange() {
    resetResults();
    updateQuickStats(null);
    setStatus("Dates changed. Run analysis to load updated results.", false);
}

function handleAggregationChange() {
    resetResults();
    updateQuickStats(null);
    setStatus("Temporal aggregation updated. Run analysis to load resampled results.", false);
}

function handleResultVariableChange(event) {
    if (!enforceResultVariableSelection(event && event.target ? event.target : null)) {
        updateRunButtonState();
        return;
    }

    updateRunButtonState();
    applySelectedResultVariableView({
        hasResults: hasCompletedAnalysis,
        syncOverlays: true
    });

    if (!hasCompletedAnalysis) {
        setStatus("Result variables updated. Run analysis to load matching results.", false);
        return;
    }

    var selectedVariables = getSelectedResultVariables();
    var hasNewRequestedVariable = selectedVariables.some(function (variableKey) {
        return lastRequestedVariables.indexOf(variableKey) === -1;
    });

    if (hasNewRequestedVariable) {
        setStatus("Result variables updated. Run analysis again to load newly added overlays.", false);
        return;
    }

    setStatus("Result variables updated.", false);
}

catchmentSelect.addEventListener("change", handleFilterChange);
startDateInput.addEventListener("change", handleDateChange);
endDateInput.addEventListener("change", handleDateChange);
if (aggregationSelect) {
    aggregationSelect.addEventListener("change", handleAggregationChange);
}
resultVariableInputs.forEach(function (input) {
    input.addEventListener("change", handleResultVariableChange);
});

if (burnedOverlayToggle) {
    burnedOverlayToggle.addEventListener("change", syncBurnedAreaOverlay);
}

if (lakesLayerToggle) {
    lakesLayerToggle.addEventListener("change", syncLakesLayer);
}

if (temperatureOverlayToggle) {
    temperatureOverlayToggle.addEventListener("change", syncTemperatureOverlay);
}

if (aodOverlayToggle) {
    aodOverlayToggle.addEventListener("change", syncAodOverlay);
}

if (chlaLayerToggle) {
    chlaLayerToggle.addEventListener("change", function () {
        syncLakeIndicatorLayer("chla");
    });
}

if (lswtLayerToggle) {
    lswtLayerToggle.addEventListener("change", function () {
        syncLakeIndicatorLayer("lake_surface_water_temperature");
    });
}

if (tsmLayerToggle) {
    tsmLayerToggle.addEventListener("change", function () {
        syncLakeIndicatorLayer("tsm");
    });
}

if (resetAnalysisButton) {
    resetAnalysisButton.addEventListener("click", resetAnalysisUiState);
}

runButton.addEventListener("click", function () {
    var id = selectedLakeCatchmentId || catchmentSelect.value;
    var start = startDateInput.value;
    var end = endDateInput.value;
    var aggregation = getSelectedAggregationMode();
    var selectedVariables = getSelectedResultVariables();
    var requestId = currentRequestId + 1;
    var selectedStartDate = start;
    var selectedEndDate = end;
    var aggregationMode = aggregation;

    if (!selectedLakeId) {
        setStatus("Please select a lake on the map first.", true);
        return;
    }

    if (!id || !start || !end) {
        setStatus("Please select a lake and both dates.", true);
        return;
    }

    if (!selectedVariables.length) {
        setStatus("Select at least one result variable.", true);
        return;
    }

    currentRequestId = requestId;
    setLoadingState(true);
    hasCompletedAnalysis = false;
    setResetButtonVisible(false);
    burnedAreaOverlayData = null;
    temperatureOverlayData = null;
    aodOverlayData = null;
    lakesGeoJsonData = null;
    removeBurnedAreaOverlay();
    removeTemperatureOverlay();
    removeAodOverlay();
    removeLakesLayer();
    updateQuickStats(null);
    setStatus("Loading analysis results...", false);
    console.log("Selected lake_id:", selectedLakeId, "Selected catchment_id:", id);
    logTemporalDebug("query_request", {
        lakeId: selectedLakeId,
        catchmentId: id,
        selectedStartDate: selectedStartDate,
        selectedEndDate: selectedEndDate,
        aggregationMode: aggregationMode,
        selectedVariables: selectedVariables
    });

    var queryUrl = buildApiUrl("/query?" + new URLSearchParams({
        catchment_id: id,
        lake_id: selectedLakeId || "",
        start_date: start,
        end_date: end,
        aggregation: aggregation,
        variables: selectedVariables.join(","),
        _ts: String(Date.now())
    }).toString());
    logTemporalDebug("query_url", {
        selectedStartDate: selectedStartDate,
        selectedEndDate: selectedEndDate,
        aggregationMode: aggregationMode,
        queryUrl: queryUrl
    });

    Promise.all([
        fetch(queryUrl, { cache: "no-store" })
            .then(function (res) {
                if (!res.ok) {
                    return res.json()
                        .catch(function () {
                            return {};
                        })
                        .then(function (payload) {
                            throw new Error(payload.error || "API request failed");
                        });
                }
                return res.json();
            }),
        fetch(buildApiUrl("/lakes?catchment_id=" + encodeURIComponent(id)))
            .then(function (res) {
                if (!res.ok) {
                    return res.json()
                        .catch(function () {
                            return {};
                        })
                        .then(function (payload) {
                            throw new Error(payload.error || "Lakes request failed");
                        });
                }
                return res.json();
            })
    ])
        .then(function (responses) {
            if (requestId !== currentRequestId) {
                return;
            }

            var payload = responses[0];
            var lakesData = responses[1];
            var records = Array.isArray(payload) ? payload : (payload.records || []);
            var overlay = Array.isArray(payload) ? null : payload.overlay;
            var temperatureOverlayPayload = Array.isArray(payload) ? null : payload.temperature_overlay;
            var aodOverlayPayload = Array.isArray(payload) ? null : payload.aod_overlay;
            var chlaOverlayPayload = Array.isArray(payload) ? null : payload.chla_overlay;
            var lswtOverlayPayload = Array.isArray(payload) ? null : payload.lswt_overlay;
            var tsmOverlayPayload = Array.isArray(payload) ? null : payload.tsm_overlay;
            var requestedVariables = Array.isArray(payload) ? selectedVariables : (payload.selected_variables || selectedVariables);
            lastRequestedAggregation = Array.isArray(payload) ? aggregation : (payload.aggregation || aggregation);
            var summary = Array.isArray(payload) ? null : payload.summary;

            logTemporalDebug("raw_payload", {
                requestStartDate: start,
                requestEndDate: end,
                aggregation: lastRequestedAggregation,
                payloadRecords: records,
                payload: payload
            });

            renderResults(
                records,
                overlay,
                temperatureOverlayPayload,
                aodOverlayPayload,
                chlaOverlayPayload,
                lswtOverlayPayload,
                tsmOverlayPayload,
                lakesData,
                summary,
                requestedVariables
            );
            exportButton.disabled = !records.length;
            highlightCatchment(id);
            setStatus("Analysis complete.", false);
        })
        .catch(function (err) {
            if (requestId !== currentRequestId) {
                return;
            }

            console.error(err);
            resetResults(false);
            setStatus(err && err.message ? err.message : "Could not load data from the API.", true);
        })
        .finally(function () {
            if (requestId === currentRequestId) {
                setLoadingState(false);
            }
        });
});

if (toggleControlsButton) {
    toggleControlsButton.addEventListener("click", function () {
        setControlsCollapsed(!controlPanel.classList.contains("is-collapsed"));
    });
}

if (showMapButton) {
    showMapButton.addEventListener("click", function () {
        setResultsPanelOpen(false);
    });
}

if (showResultsButton) {
    showResultsButton.addEventListener("click", function () {
        setResultsPanelOpen(true);
    });
}

if (closeResultsButton) {
    closeResultsButton.addEventListener("click", function () {
        setResultsPanelOpen(false);
    });
}

if (resultsBackdrop) {
    resultsBackdrop.addEventListener("click", function () {
        setResultsPanelOpen(false);
    });
}

document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
        setResultsPanelOpen(false);
    }
});

window.addEventListener("resize", function () {
    if (resultsChart && appShell.classList.contains("is-results-open")) {
        resultsChart.resize();
    }

    map.invalidateSize();
});

exportButton.addEventListener("click", exportResultsAsCsv);
setControlsCollapsed(false);
setResultsPanelOpen(false);
setSelectedLakeDisplay(null);
updateRunButtonState();
applySelectedResultVariableView({
    hasResults: false,
    syncOverlays: false
});
updateQuickStats(null);
loadAoiBounds();
loadCatchmentsGeoJSON();
loadLakesOverview().catch(function (error) {
    console.error("Lakes overview ERROR:", error);
    setStatus(error.message, true);
});
