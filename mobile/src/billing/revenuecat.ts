import Purchases, {
  PACKAGE_TYPE,
  PURCHASES_ERROR_CODE,
  type PurchasesError,
  type PurchasesPackage,
} from 'react-native-purchases';

import { config } from '@/config';
import { useAppStore } from '@/state/app';

/**
 * RevenueCat in the family app (CLAUDE.md §10). The app only *starts* purchases: the server
 * confirms them with RevenueCat and decides access (GET /access). Nothing here unlocks
 * anything. Elders never see purchase UI (§1), so every entry point refuses elder mode.
 * SDK: https://www.revenuecat.com/docs/getting-started/installation/reactnative
 */

export class ElderModeError extends Error {
  constructor() {
    super('Purchases are never available on an elder’s phone.');
  }
}

export function billingAvailable(): boolean {
  return Boolean(config.revenuecatKey);
}

// configure() runs once per app launch; after that, switching people is logIn/logOut.
let configured = false;
let signedInAs: string | null = null;

/** Configure the SDK for this family member (our user id is RevenueCat's App User ID, the
 * id the server asks RevenueCat about), and say which family the next purchase is for. */
export async function prepareBilling(userId: string, familyId: string): Promise<void> {
  if (useAppStore.getState().mode === 'elder') {
    throw new ElderModeError();
  }
  if (!config.revenuecatKey) {
    throw new Error('Purchases aren’t set up in this build.');
  }
  if (!configured) {
    Purchases.configure({ apiKey: config.revenuecatKey, appUserID: userId });
    configured = true;
    signedInAs = userId;
  } else if (signedInAs !== userId) {
    await Purchases.logIn(userId);
    signedInAs = userId;
  }
  // The webhook uses this to credit the right family (a member can be in several).
  await Purchases.setAttributes({ family_id: familyId });
}

export interface PlusPackages {
  dayPass?: PurchasesPackage;
  monthly?: PurchasesPackage;
  annual?: PurchasesPackage;
}

export async function plusPackages(): Promise<PlusPackages> {
  const offerings = await Purchases.getOfferings();
  const packages = offerings.current?.availablePackages ?? [];
  return {
    dayPass: packages.find((pkg) => pkg.product.identifier === 'day_pass'),
    monthly: packages.find((pkg) => pkg.packageType === PACKAGE_TYPE.MONTHLY),
    annual: packages.find((pkg) => pkg.packageType === PACKAGE_TYPE.ANNUAL),
  };
}

/** Start a purchase. 'cancelled' when the person backed out; errors otherwise. */
export async function buy(pkg: PurchasesPackage): Promise<'done' | 'cancelled'> {
  if (useAppStore.getState().mode === 'elder') {
    throw new ElderModeError();
  }
  try {
    await Purchases.purchasePackage(pkg);
    return 'done';
  } catch (error) {
    if ((error as PurchasesError).code === PURCHASES_ERROR_CODE.PURCHASE_CANCELLED_ERROR) {
      return 'cancelled';
    }
    throw error;
  }
}

export async function restore(): Promise<void> {
  if (useAppStore.getState().mode === 'elder') {
    throw new ElderModeError();
  }
  await Purchases.restorePurchases();
}

/** On sign-out, so the next person's purchases aren't mixed with this one's. */
export async function forgetBillingUser(): Promise<void> {
  if (signedInAs !== null) {
    signedInAs = null;
    try {
      await Purchases.logOut();
    } catch {
      // Already anonymous.
    }
  }
}
