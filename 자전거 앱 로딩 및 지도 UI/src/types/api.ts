export interface Coordinate {
  lat: number;
  lng: number;
}

export interface CoreMeta {
  generated_at?: string | null;
  horizon?: string | null;
  demo_mode?: boolean;
  [key: string]: unknown;
}

export interface CoreStation {
  station_id: string;
  station_name: string;
  location: Coordinate;
  weather: {
    precip_band: string;
    temperature_c?: number | null;
  };
  ml: {
    broken_suspected_count: number;
  };
  stgnn: {
    predicted_net_flow: number;
    shortage_pressure: number;
  };
  available_bikes?: number;
  capacity?: number;
  [key: string]: unknown;
}

export interface ScenarioDriver {
  driver_id: string;
  driver_name: string;
  start_at: string;
  start_location: Coordinate;
  vehicle_capacity: number;
  end_at?: string | null;
}

export interface CoreScenario {
  core: {
    meta: CoreMeta;
    stations: CoreStation[];
  };
  drivers?: ScenarioDriver[] | null;
  driver_count: number;
  vehicle_capacity: number;
  start_at?: string | null;
  work_minutes: number;
  reserve_bikes_per_source: number;
  service_minutes_per_stop: number;
  use_tmap: boolean;
}

export type MissionStatus =
  | "offered"
  | "accepted"
  | "in_progress"
  | "completed"
  | "cancelled";

export type StopAction = "pickup" | "dropoff";
export type StopStatus = "pending" | "completed" | "skipped";
export type RewardStatus = "pending" | "approved" | "rejected" | "reversed";

export interface RewardBreakdown {
  base_points: number;
  priority_bonus_points: number;
  completion_bonus_points: number;
  total_points: number;
}

export interface NavigationInstruction {
  sequence: number;
  description: string;
  location: Coordinate;
  point_type: string | null;
  turn_type: number | null;
  road_name: string | null;
  distance_meters: number;
  duration_seconds: number;
  arrive_at: string | null;
  complete_at: string | null;
}

export interface RoadNavigation {
  provider: "tmap";
  total_distance_meters: number;
  total_duration_seconds: number;
  total_fare_won: number;
  coordinates: Coordinate[];
  instructions: NavigationInstruction[];
}

export interface PlannedStop {
  sequence: number;
  action: StopAction;
  station_id: string;
  station_name: string;
  location: Coordinate;
  quantity: number;
  load_after: number;
  capacity: number;
  leg_distance_km: number;
  eta: string;
  etd: string;
  available_bikes_at_plan_time: number | null;
  predicted_net_flow: number;
  shortage_pressure: number;
  precip_band: string;
}

export interface Transfer {
  transfer_id: string;
  source_station_id: string;
  source_station_name: string;
  destination_station_id: string;
  destination_station_name: string;
  quantity: number;
  shortage_pressure: number;
  direct_distance_km: number;
  pickup_eta: string;
  dropoff_eta: string;
}

export interface DriverRoute {
  driver_id: string;
  driver_name: string;
  route_color: string;
  start_at: string;
  end_at: string | null;
  start_location: Coordinate;
  vehicle_capacity: number;
  status: "assigned" | "idle";
  total_bikes_moved: number;
  total_distance_km: number;
  estimated_finish_at: string;
  first_pickup_distance_km: number | null;
  first_pickup_travel_seconds: number | null;
  transfers: Transfer[];
  stops: PlannedStop[];
  navigation: RoadNavigation | null;
}

export interface PlanMapRoute {
  driver_id: string;
  color: string;
  geometry_source: "straight_line_preview" | "tmap_vehicle_route";
  coordinates: Coordinate[];
}

export interface PlanMapMarker {
  marker_type: "driver_start" | "pickup" | "dropoff";
  driver_id: string;
  sequence: number;
  location: Coordinate;
  label: string;
  station_id: string | null;
  quantity: number | null;
}

export interface PlanResponse {
  plan_id: string;
  generated_at: string;
  status: "fully_assigned" | "partially_assigned" | "no_assignment";
  data_sources: {
    demand_forecast: string;
    live_inventory:
      | "official_tashu_openapi"
      | "provided_tashu_snapshot"
      | "prediction_only";
    live_snapshot_station_count: number;
    live_station_match_count: number;
    core_station_count: number;
    allocation_travel_time: "tmap_route_matrix" | "haversine_estimate";
    allocation_strategy: "nearest_home_seed_then_road_time_greedy_local_search";
    distance:
      | "haversine_straight_line"
      | "tmap_vehicle_route"
      | "mixed_tmap_and_haversine";
  };
  summary: {
    driver_count: number;
    active_driver_count: number;
    transfer_count: number;
    total_bikes_requested: number;
    total_bikes_moved: number;
    total_shortage_unresolved: number;
    total_surplus_unassigned: number;
    broken_bikes_excluded: number;
  };
  routes: DriverRoute[];
  unresolved: Array<{
    station_id: string;
    station_name: string;
    kind: "shortage" | "surplus";
    remaining_quantity: number;
    reason:
      | "insufficient_usable_supply"
      | "outside_driver_work_window"
      | "below_min_transfer"
      | "surplus_after_all_shortages_filled";
  }>;
  map_data: {
    geometry_source:
      | "straight_line_preview"
      | "tmap_vehicle_route"
      | "mixed_tmap_and_straight_line";
    center: Coordinate;
    bounds: {
      southwest: Coordinate;
      northeast: Coordinate;
    };
    routes: PlanMapRoute[];
    markers: PlanMapMarker[];
  };
  warnings: string[];
  published_mission_ids: string[];
}

export interface MissionStop {
  sequence: number;
  action: StopAction;
  station_id: string;
  station_name: string;
  location: Coordinate;
  planned_quantity: number;
  actual_quantity: number | null;
  status: StopStatus;
  shortage_pressure: number;
  qr_verification: "not_required" | "pending" | "verified";
  qr_verified_at: string | null;
  qr_verified_location: Coordinate | null;
  bike_qr_count: number;
  completed_location: Coordinate | null;
  distance_from_station_meters: number | null;
  evidence_photo_url: string | null;
  skipped_reason: string | null;
  completed_at: string | null;
}

export interface MissionSummary {
  mission_id: string;
  plan_id: string;
  driver_id: string;
  driver_name: string;
  status: MissionStatus;
  total_stops: number;
  completed_stops: number;
  planned_bikes: number;
  first_pickup: MissionStop | null;
  estimated_reward: RewardBreakdown;
  awarded_reward: RewardBreakdown | null;
  reward_status: RewardStatus | null;
  cancelled_reason: string | null;
  offered_at: string;
  accepted_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface MissionDetail extends MissionSummary {
  stops: MissionStop[];
  route: DriverRoute;
  gps_completion_radius_meters: number;
}

export interface Wallet {
  driver_id: string;
  balance_points: number;
  lifetime_earned_points: number;
  completed_mission_count: number;
  pending_points: number;
  reversed_points: number;
  updated_at: string | null;
}

export interface RewardTransaction {
  transaction_id: string;
  driver_id: string;
  mission_id: string;
  points: number;
  reason: string;
  status: RewardStatus;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_reason: string | null;
  fraud_score: number;
  settlement_id: string | null;
  breakdown: RewardBreakdown;
  created_at: string;
}

export interface OperationsBootstrap {
  driver_id: string;
  missions: MissionSummary[];
  wallet: Wallet;
}

export interface StationQr {
  station_id: string;
  qr_payload: string;
  svg_data_url: string;
}

export interface QrChallenge {
  challenge_id: string;
  mission_id: string;
  sequence: number;
  expires_at: string;
}

export interface DriverLivePosition {
  driver_id: string;
  location: Coordinate;
  recorded_at: string;
  accuracy_meters: number;
  speed_kmh: number | null;
  anomaly: string | null;
  active_mission_id: string | null;
}

export interface TestDeviceAssignment {
  device_id: string;
  scenario_id: string;
  driver_id: string;
  driver_name: string;
  plan_id: string;
  revision: number;
  bound_at: string;
}

export interface TestDriverState {
  scenario_id: string;
  driver_id: string;
  mission_id: string | null;
  mission_status: MissionStatus | null;
  current_location: Coordinate | null;
  next_stop: MissionStop | null;
  arrived: boolean;
  movement_version: number;
}

export interface MissionListResponse {
  count: number;
  missions: MissionSummary[];
}

export interface RewardTransactionListResponse {
  count: number;
  transactions: RewardTransaction[];
}
