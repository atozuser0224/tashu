$ErrorActionPreference = "Stop"

$baseUrl = "http://127.0.0.1:8765"
$adminHeaders = @{ "X-Test-Role" = "admin" }

function Invoke-JsonPost {
    param(
        [string] $Uri,
        [hashtable] $Headers,
        [object] $Body
    )

    $parameters = @{
        Uri = $Uri
        Method = "Post"
        Headers = $Headers
    }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json"
        $parameters.Body = $Body | ConvertTo-Json -Depth 10
    }
    Invoke-RestMethod @parameters
}

$status = Invoke-RestMethod "$baseUrl/api/v1/test/status"
Invoke-JsonPost "$baseUrl/api/v1/test/reset" $adminHeaders $null | Out-Null
$plan = Invoke-JsonPost "$baseUrl/api/v1/test/demo/plan" $adminHeaders $null
$missions = Invoke-RestMethod "$baseUrl/api/v1/operations/missions" -Headers $adminHeaders
$missionId = $missions.missions[0].mission_id
$mission = Invoke-RestMethod "$baseUrl/api/v1/operations/missions/$missionId" -Headers $adminHeaders
$driverId = $mission.driver_id
$driverHeaders = @{
    "X-Test-Role" = "driver"
    "X-Test-Driver-Id" = $driverId
}
$action = @{ driver_id = $driverId }

Invoke-JsonPost "$baseUrl/api/v1/operations/missions/$missionId/accept" $driverHeaders $action | Out-Null
Invoke-JsonPost "$baseUrl/api/v1/operations/missions/$missionId/start" $driverHeaders $action | Out-Null

$loadedBikes = [System.Collections.Generic.List[string]]::new()
foreach ($stop in $mission.stops) {
    $location = @{
        location = $stop.location
        recorded_at = [DateTimeOffset]::UtcNow.ToString("o")
        accuracy_meters = 3
        speed_kmh = 0
        device_id = "test-panel-http"
    }
    Invoke-JsonPost "$baseUrl/api/v1/operations/drivers/me/location" $driverHeaders $location | Out-Null

    if ($stop.action -eq "pickup") {
        $bikeCodes = @()
        foreach ($index in 1..$stop.planned_quantity) {
            $bikeCode = "TEST-$missionId-$($stop.sequence)-$index"
            $bikeCodes += $bikeCode
            $loadedBikes.Add($bikeCode)
        }
    }
    else {
        $stationQr = Invoke-JsonPost "$baseUrl/api/v1/test/stations/$($stop.station_id)/qr" $adminHeaders $null
        $challengeBody = @{
            driver_id = $driverId
            device_id = "test-panel-http"
        }
        $challenge = Invoke-JsonPost "$baseUrl/api/v1/operations/missions/$missionId/stops/$($stop.sequence)/qr-challenge" $driverHeaders $challengeBody
        $verifyBody = @{
            driver_id = $driverId
            location = $stop.location
            qr_payload = $stationQr.qr_payload
            challenge_id = $challenge.challenge_id
            device_id = "test-panel-http"
            integrity_provider = "development"
        }
        Invoke-JsonPost "$baseUrl/api/v1/operations/missions/$missionId/stops/$($stop.sequence)/verify-qr" $driverHeaders $verifyBody | Out-Null

        $bikeCodes = @($loadedBikes | Select-Object -First $stop.planned_quantity)
        foreach ($bikeCode in $bikeCodes) {
            $loadedBikes.Remove($bikeCode) | Out-Null
        }
    }

    $completeBody = @{
        driver_id = $driverId
        location = $stop.location
        actual_quantity = $stop.planned_quantity
        bike_qr_codes = $bikeCodes
    }
    Invoke-JsonPost "$baseUrl/api/v1/operations/missions/$missionId/stops/$($stop.sequence)/complete" $driverHeaders $completeBody | Out-Null
}

$completed = Invoke-RestMethod "$baseUrl/api/v1/operations/missions/$missionId" -Headers $driverHeaders
[ordered]@{
    test_mode = $status.test_mode
    api_version = (Invoke-RestMethod "$baseUrl/openapi.json").info.version
    plan_id = $plan.plan_id
    driver_id = $driverId
    mission_id = $missionId
    mission_status = $completed.status
    completed_stops = @($completed.stops | Where-Object status -eq "completed").Count
    qr_verified_stops = @($completed.stops | Where-Object qr_verification -eq "verified").Count
    awarded_points = $completed.awarded_reward.total_points
} | ConvertTo-Json -Compress
