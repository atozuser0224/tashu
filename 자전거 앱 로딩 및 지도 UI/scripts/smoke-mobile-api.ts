import { createApiClient } from '../src/services/api';

const baseUrl = process.env.RIDEGO_SMOKE_API_URL || 'http://127.0.0.1:8765';
const driverId = process.env.RIDEGO_SMOKE_DRIVER_ID || 'DRIVER-01';
const api = createApiClient({ baseUrl, driverId, deviceId: 'ridego-mobile-smoke' });

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function main() {
  const reset = await api.resetTestData();
  assert(reset.reset, '테스트 데이터 초기화에 실패했습니다.');
  const scenario = await api.sampleCore();
  scenario.use_tmap = false;
  const plan = await api.createCorePlan(scenario);
  assert(plan.published_mission_ids.length > 0, '계획에서 미션이 발행되지 않았습니다.');
  assert(plan.map_data.routes.some((route) => route.coordinates.length > 1), '지도 경로 좌표가 없습니다.');

  const summaries = await api.listMissions();
  const summary = summaries.find((mission) => mission.plan_id === plan.plan_id);
  assert(summary, `${driverId}에 새 계획 미션이 배정되지 않았습니다.`);

  let mission = await api.getMission(summary.mission_id);
  if (mission.status === 'offered') mission = await api.acceptMission(mission.mission_id);
  if (mission.status === 'accepted') mission = await api.startMission(mission.mission_id);
  assert(mission.status === 'in_progress', `미션 시작 상태가 올바르지 않습니다: ${mission.status}`);

  const loadedBikeCodes: string[] = [];
  for (const stop of mission.stops) {
    if (stop.status === 'completed') continue;
    await api.reportLocation(stop.location, { accuracyMeters: 3 });

    if (stop.action === 'pickup') {
      const codes = Array.from(
        { length: stop.planned_quantity },
        (_, index) => `MOBILE-${plan.plan_id}-${stop.sequence}-${index + 1}`,
      );
      mission = await api.completeStop(mission.mission_id, stop.sequence, {
        location: stop.location,
        actualQuantity: stop.planned_quantity,
        bikeQrCodes: codes,
      });
      loadedBikeCodes.push(...codes);
      continue;
    }

    const [stationQr, challenge] = await Promise.all([
      api.createStationQr(stop.station_id),
      api.createQrChallenge(mission.mission_id, stop.sequence),
    ]);
    mission = await api.verifyStationQr(mission.mission_id, stop.sequence, {
      location: stop.location,
      qrPayload: stationQr.qr_payload,
      challengeId: challenge.challenge_id,
      integrityProvider: 'development',
    });
    const deployed = loadedBikeCodes.splice(0, stop.planned_quantity);
    assert(deployed.length === stop.planned_quantity, '배치할 적재 자전거 QR이 부족합니다.');
    mission = await api.completeStop(mission.mission_id, stop.sequence, {
      location: stop.location,
      actualQuantity: deployed.length,
      bikeQrCodes: deployed,
    });
  }

  assert(mission.status === 'completed', `미션이 완료되지 않았습니다: ${mission.status}`);
  assert(mission.stops.every((stop) => stop.status === 'completed'), '완료되지 않은 정차가 있습니다.');

  const [wallet, transactions] = await Promise.all([api.getWallet(), api.getTransactions()]);
  const reward = transactions.find((transaction) => transaction.mission_id === mission.mission_id);
  assert(reward, '완료 미션의 리워드 거래가 생성되지 않았습니다.');

  console.log(JSON.stringify({
    ok: true,
    baseUrl,
    planId: plan.plan_id,
    missionId: mission.mission_id,
    routeCount: plan.map_data.routes.length,
    routeGeometry: plan.map_data.geometry_source,
    stopsCompleted: mission.completed_stops,
    rewardPoints: reward.points,
    rewardStatus: reward.status,
    walletPendingPoints: wallet.pending_points,
  }));
}

main().catch((error) => {
  console.error(error instanceof Error ? `${error.name}: ${error.message}` : error);
  process.exitCode = 1;
});
