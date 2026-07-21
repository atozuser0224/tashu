import { Ionicons } from '@expo/vector-icons';
import { useMemo, useState } from 'react';
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import type { RewardStatus, RewardTransaction, Wallet } from '../types/api';

type Props = {
  onMenu: () => void;
  driverId: string;
  wallet: Wallet | null;
  transactions: RewardTransaction[];
  loading: boolean;
  onRefresh: () => void | Promise<void>;
};

const ACCENT = '#1FA35C';
const ACCENT_SOFT = '#DCF3E6';
const INK = '#201E1D';
const MUTED = '#9B9797';
const CANVAS = '#F3F2F2';

const statusMeta: Record<RewardStatus, { label: string; color: string }> = {
  pending: { label: '검토 중', color: '#8A6100' },
  approved: { label: '지급 완료', color: ACCENT },
  rejected: { label: '지급 거절', color: '#D0442A' },
  reversed: { label: '회수됨', color: '#7D7979' },
};

export function RewardsScreen({
  onMenu,
  driverId,
  wallet,
  transactions,
  loading,
  onRefresh,
}: Props) {
  const [showAll, setShowAll] = useState(false);
  const visibleTransactions = showAll ? transactions : transactions.slice(0, 3);
  const hiddenCount = Math.max(0, transactions.length - 3);
  const today = formatToday();
  const monthlyEarned = useMemo(() => calculateMonthlyEarned(transactions), [transactions]);

  return (
    <View
      style={styles.root}
      accessibilityLabel={`${driverId} 기사 리워드 화면`}
    >
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="메뉴 열기"
        onPress={onMenu}
        style={({ pressed }) => [styles.menuButton, pressed && styles.pressed]}
      >
        <Ionicons name="menu" size={23} color={INK} />
      </Pressable>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={(
          <RefreshControl
            refreshing={loading}
            onRefresh={onRefresh}
            tintColor={ACCENT}
            colors={[ACCENT]}
            progressViewOffset={72}
          />
        )}
      >
        <View style={styles.balanceCard}>
          <View style={styles.balanceHeader}>
            <Text style={styles.balanceLabel}>보유 리워드</Text>
            <Text style={styles.today}>{today}</Text>
          </View>

          <View style={styles.balanceRow}>
            <RewardCoin size={40} inverse />
            <Text style={styles.balanceValue} numberOfLines={1} adjustsFontSizeToFit>
              {formatPoints(wallet?.balance_points ?? 0)} P
            </Text>
          </View>

          <Text style={styles.balanceSummary}>
            이번 달 적립 {formatPoints(monthlyEarned)} P · 누적 재배치 {wallet?.completed_mission_count ?? 0}건
          </Text>
        </View>

        <Text style={styles.historyHeading}>적립 내역</Text>

        {!wallet && !loading ? (
          <EmptyState
            icon="cloud-offline-outline"
            title="지갑 정보를 불러오지 못했어요"
            body="서버 연결을 확인한 뒤 아래로 당겨 새로고침해 주세요."
          />
        ) : transactions.length === 0 && !loading ? (
          <EmptyState
            icon="receipt-outline"
            title="아직 적립 내역이 없어요"
            body="재배치 미션을 완료하면 지급 내역이 여기에 표시됩니다."
          />
        ) : (
          <View style={styles.transactionList}>
            {visibleTransactions.map((transaction) => (
              <TransactionRow key={transaction.transaction_id} transaction={transaction} />
            ))}
          </View>
        )}

        {transactions.length > 3 ? (
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ expanded: showAll }}
            onPress={() => setShowAll((current) => !current)}
            style={({ pressed }) => [styles.historyToggle, pressed && styles.pressed]}
          >
            <Text style={styles.historyToggleText}>
              {showAll ? '접기' : `더 보기 (${hiddenCount})`}
            </Text>
            <Ionicons
              name={showAll ? 'chevron-up' : 'chevron-down'}
              size={16}
              color="#605D5D"
            />
          </Pressable>
        ) : null}
      </ScrollView>
    </View>
  );
}

function RewardCoin({ size, inverse = false }: { size: number; inverse?: boolean }) {
  return (
    <View
      style={[
        styles.coinOuter,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: inverse ? 'rgba(255,255,255,0.28)' : ACCENT_SOFT,
        },
      ]}
    >
      <View
        style={[
          styles.coinInner,
          {
            width: size * 0.8,
            height: size * 0.8,
            borderRadius: size * 0.4,
            backgroundColor: inverse ? '#FFFFFF' : 'transparent',
          },
        ]}
      >
        <Text
          style={[
            styles.coinMark,
            {
              color: ACCENT,
              fontSize: size * 0.43,
            },
          ]}
        >
          ₩
        </Text>
      </View>
    </View>
  );
}

function TransactionRow({ transaction }: { transaction: RewardTransaction }) {
  const meta = statusMeta[transaction.status];
  const isDebit = transaction.points < 0 || transaction.status === 'reversed';
  const pointColor = isDebit || transaction.status === 'rejected' ? '#D0442A' : ACCENT;

  return (
    <View style={styles.transactionRow}>
      <View style={[styles.transactionIcon, isDebit && styles.transactionIconDebit]}>
        <Ionicons
          name={isDebit ? 'remove-circle-outline' : 'cash-outline'}
          size={20}
          color={pointColor}
        />
      </View>

      <View style={styles.transactionCopy}>
        <Text style={styles.transactionTitle} numberOfLines={1}>
          {rewardReason(transaction.reason)}
        </Text>
        <View style={styles.transactionMeta}>
          <Text style={styles.transactionDate}>{formatHistoryDate(transaction.created_at)}</Text>
          {transaction.status !== 'approved' ? (
            <Text style={[styles.transactionStatus, { color: meta.color }]}>· {meta.label}</Text>
          ) : null}
        </View>
      </View>

      <Text style={[styles.transactionPoints, { color: pointColor }]}>
        {transaction.points > 0 ? '+' : ''}{formatPoints(transaction.points)} P
      </Text>
    </View>
  );
}

function EmptyState({
  icon,
  title,
  body,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  body: string;
}) {
  return (
    <View style={styles.empty}>
      <Ionicons name={icon} size={30} color={MUTED} />
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

function calculateMonthlyEarned(transactions: RewardTransaction[]): number {
  const now = new Date();
  return transactions.reduce((total, transaction) => {
    const createdAt = new Date(transaction.created_at);
    const sameMonth = !Number.isNaN(createdAt.getTime())
      && createdAt.getFullYear() === now.getFullYear()
      && createdAt.getMonth() === now.getMonth();
    const earned = transaction.points > 0
      && transaction.status !== 'rejected'
      && transaction.status !== 'reversed';
    return sameMonth && earned ? total + transaction.points : total;
  }, 0);
}

function rewardReason(reason: string): string {
  const known: Record<string, string> = {
    mission_completion: '재배치 완료',
    mission_completed: '재배치 완료',
    mission_reward: '재배치 미션 리워드',
    manual_adjustment: '관리자 포인트 조정',
    fraud_reversal: '이상 활동 포인트 회수',
  };
  return known[reason] ?? reason.replaceAll('_', ' ');
}

function formatPoints(points: number): string {
  return Math.trunc(points).toLocaleString('ko-KR');
}

function formatToday(): string {
  const today = new Date();
  return [today.getFullYear(), today.getMonth() + 1, today.getDate()]
    .map((value, index) => index === 0 ? String(value) : String(value).padStart(2, '0'))
    .join('.');
}

function formatHistoryDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()]
    .map((part, index) => index === 0 ? String(part) : String(part).padStart(2, '0'))
    .join('.');
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: CANVAS,
  },
  menuButton: {
    position: 'absolute',
    top: 58,
    left: 22,
    zIndex: 10,
    width: 46,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 15,
    backgroundColor: '#FFFFFF',
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.17,
    shadowRadius: 12,
    elevation: 7,
  },
  pressed: {
    opacity: 0.68,
  },
  content: {
    paddingTop: 120,
    paddingHorizontal: 22,
    paddingBottom: 30,
  },
  balanceCard: {
    padding: 24,
    borderRadius: 24,
    backgroundColor: ACCENT,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.18,
    shadowRadius: 30,
    elevation: 10,
  },
  balanceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  balanceLabel: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
    opacity: 0.92,
  },
  today: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '600',
    opacity: 0.85,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 22,
  },
  balanceValue: {
    flex: 1,
    marginLeft: 12,
    color: '#FFFFFF',
    fontSize: 44,
    lineHeight: 48,
    fontWeight: '800',
    letterSpacing: -0.9,
  },
  balanceSummary: {
    marginTop: 18,
    color: '#FFFFFF',
    fontSize: 12,
    lineHeight: 17,
    fontWeight: '500',
    opacity: 0.8,
  },
  coinOuter: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  coinInner: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  coinMark: {
    fontWeight: '900',
    lineHeight: 21,
    letterSpacing: -1,
  },
  historyHeading: {
    marginTop: 26,
    marginBottom: 12,
    color: '#605D5D',
    fontSize: 13,
    fontWeight: '700',
  },
  transactionList: {
    gap: 10,
  },
  transactionRow: {
    minHeight: 72,
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 15,
    paddingHorizontal: 16,
    borderRadius: 16,
    backgroundColor: '#FFFFFF',
  },
  transactionIcon: {
    width: 42,
    height: 42,
    flexShrink: 0,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    backgroundColor: ACCENT_SOFT,
  },
  transactionIconDebit: {
    backgroundColor: '#FBE9E5',
  },
  transactionCopy: {
    flex: 1,
    minWidth: 0,
    marginLeft: 14,
  },
  transactionTitle: {
    color: INK,
    fontSize: 14,
    fontWeight: '700',
  },
  transactionMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  transactionDate: {
    color: MUTED,
    fontSize: 12,
    fontWeight: '400',
  },
  transactionStatus: {
    marginLeft: 4,
    fontSize: 10,
    fontWeight: '700',
  },
  transactionPoints: {
    flexShrink: 0,
    marginLeft: 8,
    fontSize: 16,
    fontWeight: '800',
  },
  historyToggle: {
    width: '100%',
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 14,
    paddingVertical: 14,
    borderWidth: 1.5,
    borderColor: '#E2E0DD',
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
  },
  historyToggleText: {
    marginRight: 6,
    color: '#605D5D',
    fontSize: 14,
    fontWeight: '700',
  },
  empty: {
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingVertical: 30,
    borderRadius: 16,
    backgroundColor: '#FFFFFF',
  },
  emptyTitle: {
    marginTop: 10,
    color: INK,
    fontSize: 14,
    fontWeight: '700',
  },
  emptyBody: {
    marginTop: 6,
    color: MUTED,
    fontSize: 11,
    lineHeight: 17,
    textAlign: 'center',
  },
});
