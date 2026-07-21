import type { ComponentProps } from 'react';
import { useMemo, useState } from 'react';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

type Gender = '남성' | '여성';

export type DriverProfile = {
  name: string;
  birthDate: string;
  birthYear: string;
  gender: Gender;
  residence: string;
  phone: string;
};

type DraftProfile = Omit<DriverProfile, 'birthYear' | 'gender'> & { gender: Gender | '' };

const ADDRESS_OPTIONS = [
  '대전광역시 유성구 대학로 99',
  '대전광역시 유성구 엑스포로 32',
  '대전광역시 유성구 계룡로 121',
  '대전광역시 유성구 온천로 45',
  '대전광역시 유성구 유성대로 668',
  '대전광역시 서구 둔산로 100',
  '대전광역시 서구 계룡로 314',
  '대전광역시 중구 대종로 480',
  '대전광역시 유성구 봉명동 536',
];

const EMPTY_PROFILE: DraftProfile = {
  name: '',
  birthDate: '',
  gender: '',
  residence: '',
  phone: '',
};

export function ProfileSetupScreen({ onComplete }: { onComplete: (profile: DriverProfile) => void }) {
  const [profile, setProfile] = useState<DraftProfile>(EMPTY_PROFILE);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const birthDate = useMemo(() => parseBirthDate(profile.birthDate), [profile.birthDate]);
  const age = birthDate ? calculateAge(birthDate) : null;
  const birthComplete = profile.birthDate.length === 10;
  const birthError = birthComplete && !birthDate
    ? '올바른 생년월일을 입력해 주세요.'
    : age !== null && age < 24
      ? '만 24세 미만은 이용할 수 없습니다.'
      : null;
  const phoneDigits = profile.phone.replace(/\D/g, '');
  const valid = profile.name.trim().length >= 2
    && birthDate !== null
    && age !== null
    && age >= 24
    && profile.gender !== ''
    && profile.residence.trim().length >= 3
    && phoneDigits.length >= 10;

  const suggestions = useMemo(() => {
    const query = normalizeAddress(profile.residence);
    if (!showSuggestions || !query) return [];
    return ADDRESS_OPTIONS
      .filter((address) => normalizeAddress(address).includes(query) && address !== profile.residence)
      .slice(0, 5);
  }, [profile.residence, showSuggestions]);

  const update = <Key extends keyof DraftProfile>(key: Key, value: DraftProfile[Key]) => {
    setProfile((current) => ({ ...current, [key]: value }));
  };

  const submit = () => {
    if (!valid || profile.gender === '') return;
    onComplete({
      ...profile,
      name: profile.name.trim(),
      residence: profile.residence.trim(),
      birthYear: profile.birthDate.slice(0, 4),
      gender: profile.gender,
    });
  };

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
      <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <Text style={styles.title}>정보 입력</Text>
          <Text style={styles.subtitle}>서비스 이용을 위해 인적사항을 입력해 주세요</Text>
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.form}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Field
            label="이름"
            value={profile.name}
            onChangeText={(value) => update('name', value)}
            placeholder="홍길동"
            autoCapitalize="words"
            returnKeyType="next"
          />

          <Field
            label="생년월일"
            value={profile.birthDate}
            onChangeText={(value) => update('birthDate', formatBirthDate(value))}
            placeholder="YYYY-MM-DD"
            keyboardType="number-pad"
            maxLength={10}
            error={birthError ?? undefined}
          />

          <View style={styles.field}>
            <Text style={styles.label}>성별</Text>
            <View style={styles.genderRow}>
              <GenderButton
                label="남성"
                active={profile.gender === '남성'}
                activeColor="#2F6FED"
                onPress={() => update('gender', '남성')}
              />
              <GenderButton
                label="여성"
                active={profile.gender === '여성'}
                activeColor="#E6559B"
                onPress={() => update('gender', '여성')}
              />
            </View>
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>거주지</Text>
            <TextInput
              value={profile.residence}
              onFocus={() => setShowSuggestions(true)}
              onChangeText={(value) => {
                update('residence', value);
                setShowSuggestions(true);
              }}
              placeholder="도로명·건물명으로 검색"
              placeholderTextColor="#A9A5A1"
              style={styles.input}
              returnKeyType="next"
            />
            {suggestions.length > 0 ? (
              <View style={styles.suggestions}>
                {suggestions.map((address, index) => (
                  <Pressable
                    key={address}
                    onPress={() => {
                      update('residence', address);
                      setShowSuggestions(false);
                    }}
                    style={({ pressed }) => [
                      styles.suggestion,
                      index < suggestions.length - 1 && styles.suggestionDivider,
                      pressed && styles.suggestionPressed,
                    ]}
                  >
                    <Ionicons name="location-outline" size={16} color="#F7941D" />
                    <Text style={styles.suggestionText}>{address}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
          </View>

          <Field
            label="전화번호"
            value={profile.phone}
            onChangeText={(value) => update('phone', formatPhone(value))}
            placeholder="010-1234-5678"
            keyboardType="phone-pad"
            maxLength={13}
            returnKeyType="done"
          />
        </ScrollView>

        <View style={styles.footer}>
          <Pressable
            accessibilityRole="button"
            disabled={!valid}
            onPress={submit}
            style={({ pressed }) => [styles.completeButton, !valid && styles.completeButtonDisabled, pressed && valid && styles.completeButtonPressed]}
          >
            <Text style={styles.completeLabel}>완료</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Field({ label, error, style, ...props }: ComponentProps<typeof TextInput> & { label: string; error?: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        placeholderTextColor="#A9A5A1"
        style={[styles.input, error ? styles.inputError : null, style]}
        {...props}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

function GenderButton({
  label,
  active,
  activeColor,
  onPress,
}: {
  label: Gender;
  active: boolean;
  activeColor: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => [
        styles.genderButton,
        active && { borderColor: activeColor, backgroundColor: activeColor },
        pressed && styles.genderButtonPressed,
      ]}
    >
      <Text style={[styles.genderLabel, active && styles.genderLabelActive]}>{label}</Text>
    </Pressable>
  );
}

function formatBirthDate(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 4) return digits;
  if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
}

function formatPhone(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  if (digits.length <= 3) return digits;
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`;
  return `${digits.slice(0, 3)}-${digits.slice(3, digits.length - 4)}-${digits.slice(-4)}`;
}

function parseBirthDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  if (date.getTime() > Date.now()) return null;
  return date;
}

function calculateAge(birthDate: Date): number {
  const today = new Date();
  let age = today.getFullYear() - birthDate.getFullYear();
  const monthDifference = today.getMonth() - birthDate.getMonth();
  if (monthDifference < 0 || (monthDifference === 0 && today.getDate() < birthDate.getDate())) age -= 1;
  return age;
}

function normalizeAddress(value: string): string {
  return value.replace(/\s/g, '').toLocaleLowerCase('ko-KR');
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#F3F2F2',
  },
  root: {
    flex: 1,
    backgroundColor: '#F3F2F2',
  },
  header: {
    paddingHorizontal: 24,
    paddingTop: Platform.OS === 'web' ? 74 : 20,
    paddingBottom: 18,
  },
  title: {
    color: '#201E1D',
    fontSize: 26,
    lineHeight: 30,
    fontWeight: '800',
    letterSpacing: -0.8,
  },
  subtitle: {
    marginTop: 7,
    color: '#9B9797',
    fontSize: 13,
    fontWeight: '500',
  },
  scroll: {
    flex: 1,
  },
  form: {
    paddingHorizontal: 24,
    paddingTop: 6,
    paddingBottom: 20,
  },
  field: {
    marginBottom: 18,
  },
  label: {
    marginBottom: 8,
    color: '#605D5D',
    fontSize: 12,
    fontWeight: '700',
  },
  input: {
    width: '100%',
    minHeight: 50,
    paddingHorizontal: 16,
    paddingVertical: 13,
    borderWidth: 1.5,
    borderColor: '#E2E0DD',
    borderRadius: 12,
    color: '#201E1D',
    fontSize: 15,
    backgroundColor: '#FFFFFF',
  },
  inputError: {
    borderColor: '#D0442A',
  },
  error: {
    marginTop: 8,
    color: '#D0442A',
    fontSize: 12.5,
    fontWeight: '600',
  },
  genderRow: {
    flexDirection: 'row',
    gap: 10,
  },
  genderButton: {
    flex: 1,
    minHeight: 50,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 14,
    borderWidth: 1.5,
    borderColor: '#E2E0DD',
    borderRadius: 12,
    backgroundColor: '#FFFFFF',
  },
  genderButtonPressed: {
    opacity: 0.86,
  },
  genderLabel: {
    color: '#201E1D',
    fontSize: 15,
    fontWeight: '700',
  },
  genderLabelActive: {
    color: '#FFFFFF',
  },
  suggestions: {
    marginTop: 8,
    overflow: 'hidden',
    borderWidth: 1.5,
    borderColor: '#EEEEEE',
    borderRadius: 12,
    backgroundColor: '#FFFFFF',
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 4,
  },
  suggestion: {
    minHeight: 47,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
    paddingHorizontal: 14,
    paddingVertical: 13,
  },
  suggestionDivider: {
    borderBottomWidth: 1,
    borderBottomColor: '#F2F0ED',
  },
  suggestionPressed: {
    backgroundColor: '#FAF8F6',
  },
  suggestionText: {
    flex: 1,
    color: '#201E1D',
    fontSize: 14,
  },
  footer: {
    paddingHorizontal: 24,
    paddingTop: 14,
    paddingBottom: 24,
    borderTopWidth: 1,
    borderTopColor: '#E6E4E1',
    backgroundColor: '#F3F2F2',
  },
  completeButton: {
    minHeight: 54,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
    borderRadius: 14,
    backgroundColor: '#F7941D',
  },
  completeButtonDisabled: {
    opacity: 0.45,
  },
  completeButtonPressed: {
    backgroundColor: '#D06A0E',
  },
  completeLabel: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: -0.1,
  },
});
