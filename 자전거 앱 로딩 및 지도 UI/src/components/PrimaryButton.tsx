import type { ComponentProps } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';

import { colors, fonts } from '../theme';

type Props = ComponentProps<typeof Pressable> & {
  label: string;
  loading?: boolean;
  tone?: 'orange' | 'green' | 'dark' | 'light' | 'danger';
  compact?: boolean;
};

export function PrimaryButton({
  label,
  loading = false,
  tone = 'orange',
  compact = false,
  disabled,
  style,
  ...props
}: Props) {
  const isLight = tone === 'light';
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      style={(state) => [
        styles.base,
        compact && styles.compact,
        toneStyles[tone],
        (disabled || loading) && styles.disabled,
        state.pressed && styles.pressed,
        typeof style === 'function' ? style(state) : style,
      ]}
      {...props}
    >
      {loading ? (
        <ActivityIndicator color={isLight ? colors.ink : colors.paper} />
      ) : (
        <Text style={[styles.label, isLight && styles.labelDark]}>{label}</Text>
      )}
    </Pressable>
  );
}

const toneStyles = StyleSheet.create({
  orange: { backgroundColor: colors.orange },
  green: { backgroundColor: colors.green },
  dark: { backgroundColor: colors.navy },
  light: { backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.line },
  danger: { backgroundColor: colors.danger },
});

const styles = StyleSheet.create({
  base: {
    minHeight: 52,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 22,
  },
  compact: { minHeight: 42, borderRadius: 14, paddingHorizontal: 16 },
  label: { color: colors.paper, fontFamily: fonts.extraBold, fontSize: 16 },
  labelDark: { color: colors.ink },
  disabled: { opacity: 0.45 },
  pressed: { transform: [{ scale: 0.985 }], opacity: 0.9 },
});
