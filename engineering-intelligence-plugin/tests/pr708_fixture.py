"""PR #708 regression fixture (TK-4303, COD availability at checkout), reduced to the code paths the reviewers flagged.

A throwaway git repo at the PR's parent state, `apply_pr()` writes the PR's changes, plus the fixture data the PR
produced: review-comment history (gh api shape, including a bot), tsc output before / after, and the ticket's criteria.
No network, no GitHub, no TakeIN checkout.
"""
import json, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "run" / "scripts"
HOOKS = HERE.parent / "hooks"

ROW = """import React from 'react';
import {TouchableOpacity, Text} from 'react-native';

type Props = {title: string; onPress: () => void; disabled?: boolean; selected?: boolean; showRadio?: boolean};

const PaymentOptionRow = ({title, onPress, disabled, selected, showRadio}: Props) => {
  return (
    <TouchableOpacity onPress={onPress} disabled={disabled}>
      {showRadio ? <Text>{selected ? 'on' : 'off'}</Text> : null}
      <Text>{title}</Text>
    </TouchableOpacity>
  );
};

export default PaymentOptionRow;
"""

SHEET_BEFORE = """import React from 'react';
import PaymentOptionRow from '../PaymentOptionRow';
import {usePayments} from '../../hooks/usePayments';

const PaymentMethodsSheet = ({hasSavedCards, addCardDisabled, onSelect, onAddCard}) => {
  const {paymentMethods} = usePayments();
  const handleSelectAddNew = () => onSelect('new');
  const handleAddNewCard = () => onAddCard();
  return (
    <>
      {paymentMethods.map(m => (
        <PaymentOptionRow key={m.id} title={m.name} onPress={() => onSelect(m.id)} />
      ))}
      <PaymentOptionRow
        title="Add New"
        onPress={hasSavedCards ? handleSelectAddNew : handleAddNewCard}
        disabled={addCardDisabled}
      />
    </>
  );
};

export default PaymentMethodsSheet;
"""

SHEET_AFTER = SHEET_BEFORE.replace("""        onPress={hasSavedCards ? handleSelectAddNew : handleAddNewCard}
        disabled={addCardDisabled}
""", """        showRadio
        onPress={handleSelectAddNew}
""")

HOOK_BEFORE = """import {useQuery} from '@tanstack/react-query';
import {getPaymentMethods} from '../api/payments';

export const usePayments = (isPickupOrder = false) => {
  const {data, isFetching} = useQuery({
    queryKey: ['payment-methods'],
    queryFn: getPaymentMethods,
    select: (res) => res.methods.filter(m => !m.isCash || !isPickupOrder),
  });
  return {paymentMethods: data ?? [], paymentMethodsLoading: isFetching};
};
"""

HOOK_AFTER = """import {useQuery} from '@tanstack/react-query';
import {getPaymentMethods} from '../api/payments';

export const usePayments = (isPickupOrder = false) => {
  const {data, isFetching, refetch} = useQuery({
    queryKey: ['payment-methods'],
    queryFn: getPaymentMethods,
    enabled: false,
    select: (res) => ({
      codAvailable: res.codAvailable,
      methods: res.methods.filter(m => (m.isCash ? !isPickupOrder && (res.codAvailable ?? true) : true)),
    }),
  });
  return {
    paymentMethods: data?.methods ?? [],
    codAvailable: data?.codAvailable,
    paymentMethodsLoading: isFetching,
    paymentMethodsFetching: isFetching,
    recheckPaymentMethods: refetch,
  };
};
"""

EFFECTS_BEFORE = """import {QueryObserverResult} from '@tanstack/react-query';
import {ICreditCard} from '../../types';

export const useCheckoutEffects = (refetchCards: () => Promise<QueryObserverResult<ICreditCard[]>>) => {
  return {refresh: () => refetchCards()};
};
"""

EFFECTS_AFTER = """import {ICreditCard} from '../../types';

export const useCheckoutEffects = (refetchCards: () => Promise<unknown>) => {
  return {refresh: () => refetchCards()};
};
"""

CHECKOUT_BEFORE = """import React from 'react';
import {Button} from 'react-native';
import PaymentMethodsSheet from '../../components/PaymentMethodsSheet';
import PlacingOrderSheet from '../../components/PlacingOrderSheet';
import PickupSheet from '../../components/PickupSheet';
import {usePayments} from '../../hooks/usePayments';
import {placeOrder} from '../../api/orders';

const Checkout = ({cart, hasSavedCards}) => {
  const {paymentMethods} = usePayments();
  const mainButtonDisabled = !cart;
  const continueReviewedOrder = () => {
    placeOrder(cart);
  };
  const handleMainCta = () => {
    continueReviewedOrder();
  };
  const onPickupContinue = () => {
    if (mainButtonDisabled) return;
    continueReviewedOrder();
  };
  return (
    <>
      <PaymentMethodsSheet hasSavedCards={hasSavedCards} addCardDisabled={false} onSelect={() => {}} onAddCard={() => {}} />
      <Button title="Place order" onPress={handleMainCta} disabled={mainButtonDisabled} />
      <PickupSheet onContinue={onPickupContinue} />
      <PlacingOrderSheet
        onPlaceNow={() => continueReviewedOrder()}
        onCountdownComplete={() => continueReviewedOrder()}
      />
    </>
  );
};

export default Checkout;
"""

CHECKOUT_AFTER = CHECKOUT_BEFORE.replace("""  const {paymentMethods} = usePayments();
  const mainButtonDisabled = !cart;""", """  const {paymentMethods, paymentMethodsFetching} = usePayments();
  const mainButtonDisabled = !cart || paymentMethodsFetching;""")

TRACKING = """import React from 'react';
import {usePayments} from '../../hooks/usePayments';

const OrderTracking = ({order}) => {
  const {paymentMethods} = usePayments();
  const method = paymentMethods.find(m => m.id === order.paymentMethodId);
  return method ? method.name : null;
};

export default OrderTracking;
"""

TRACKING_REVAMP = TRACKING.replace("OrderTracking =", "OrderTrackingRevamp =").replace("export default OrderTracking;", "export default OrderTrackingRevamp;")

WALLET = """import React from 'react';
import PaymentMethodsSheet from '../../components/PaymentMethodsSheet';

const Wallet = ({cards}) => (
  <PaymentMethodsSheet hasSavedCards={cards.length > 0} addCardDisabled={cards.length >= 5} onSelect={() => {}} onAddCard={() => {}} />
);

export default Wallet;
"""

PAYWITH_BEFORE = """import React from 'react';
import {ScaledSheet} from 'react-native-size-matters';

// design pointer for the card row (Figma 1200:300)
const PayWith = () => null;

const styles = ScaledSheet.create({
  container: {paddingHorizontal: '16@s', paddingVertical: '12@vs', borderRadius: '8@s'},
  title: {fontSize: '14@ms', marginBottom: '6@vs'},
  icon: {width: '24@s', height: '24@s'},
  subtitle: {fontSize: '12@ms', marginTop: '4@vs'},
  changeButton: {paddingHorizontal: 12, height: 32},
});

export default PayWith;
"""

PAYWITH_AFTER = PAYWITH_BEFORE.replace("""  changeButton: {paddingHorizontal: 12, height: 32},
});""", """  changeButton: {paddingHorizontal: 12, height: 32},
  // COD off with no card (Figma 7766:24478)
  addButton: {paddingHorizontal: 16,
    height: 24},
});""")

CVV = """// layout per Figma 900:12
export const CvvSheet = () => null;
"""

API = """export const getPaymentMethods = async () => ({codAvailable: true, methods: []});
"""
ORDERS = """export const placeOrder = (cart) => cart;
"""
SHEETS = {"src/components/PlacingOrderSheet/index.tsx": "export default function PlacingOrderSheet(props) { return null; }\n",
          "src/components/PickupSheet/index.tsx": "export default function PickupSheet(props) { return null; }\n"}
NAMING = """export const flags = {isFetchingCards: true, isLoadingAddress: false, isOrderFetching: false,
  cartLoading: true, menuFetching: false, isFetchingMenu: true, profileLoading: false};
"""

BEFORE = {
    "src/components/PaymentOptionRow/index.tsx": ROW,
    "src/components/PaymentMethodsSheet/index.tsx": SHEET_BEFORE,
    "src/hooks/usePayments.ts": HOOK_BEFORE,
    "src/screens/Checkout/index.tsx": CHECKOUT_BEFORE,
    "src/screens/Checkout/useCheckoutEffects.ts": EFFECTS_BEFORE,
    "src/screens/OrderTracking/index.tsx": TRACKING,
    "src/screens/OrderTracking/OrderTrackingRevamp.tsx": TRACKING_REVAMP,
    "src/screens/Wallet/index.tsx": WALLET,
    "src/screens/PayWith/index.tsx": PAYWITH_BEFORE,
    "src/components/CvvSheet.tsx": CVV,
    "src/api/payments.ts": API,
    "src/api/orders.ts": ORDERS,
    "src/state/flags.ts": NAMING,
    "package.json": json.dumps({"name": "fixture-708", "private": True}),
    **SHEETS,
}
AFTER = {
    "src/components/PaymentMethodsSheet/index.tsx": SHEET_AFTER,
    "src/hooks/usePayments.ts": HOOK_AFTER,
    "src/screens/Checkout/index.tsx": CHECKOUT_AFTER,
    "src/screens/Checkout/useCheckoutEffects.ts": EFFECTS_AFTER,
    "src/screens/PayWith/index.tsx": PAYWITH_AFTER,
}

CRITERIA = [
    {"id": "AC-1", "text": "When COD is unavailable and the customer has no saved card, show the COD row disabled and an Add card action"},
    {"id": "AC-2", "text": "A COD-gated order can't be completed by any path through the app while COD is re-checked"},
    {"id": "AC-3", "text": "The checkout response carries the COD decision, computed on the final total including the delivery fee"},
]

REVIEW_HISTORY = [  # gh api repos/{o}/{r}/pulls/comments shape, newest first
    {"user": {"login": "coderabbitai[bot]", "type": "Bot"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/700",
     "body": "Consider using ScaledSheet values and remove figma refs", "html_url": "u0"},
    {"user": {"login": "hossam", "type": "User"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/689",
     "path": "src/screens/AddressSelect/index.tsx", "body": "use the ScaledSheet suffixes here (@s / @vs)", "html_url": "u1"},
    {"user": {"login": "hossam", "type": "User"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/689",
     "body": "use isRTL helper", "html_url": "u2"},
    {"user": {"login": "kamal", "type": "User"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/681",
     "body": "rename this to isFetchingOrders please", "html_url": "u3"},
    {"user": {"login": "kamal", "type": "User"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/675",
     "body": "nit: spacing looks off on android", "html_url": "u4"},
]
FIGMA_REQUESTS = [
    {"user": {"login": "hossam", "type": "User"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/650",
     "body": "please remove the figma reference from the comment", "html_url": "f1"},
    {"user": {"login": "kamal", "type": "User"}, "pull_request_url": "https://api.github.com/repos/o/r/pulls/661",
     "body": "don't keep figma node ids in code comments", "html_url": "f2"},
]

TSC_BASELINE = """src/legacy/old.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'.
src/legacy/old.ts(22,1): error TS7006: Parameter 'x' implicitly has an 'any' type.
src/screens/Home/index.tsx(5,3): error TS2339: Property 'foo' does not exist on type 'Bar'.
"""
# after the PR: the same three, plus the consumer of the changed select shape (a file the PR did not touch)
TSC_AFTER = TSC_BASELINE + """src/screens/Checkout/CheckoutContainer.tsx(41,7): error TS2345: Argument of type '() => Promise<QueryObserverResult<{ codAvailable: boolean; methods: IPaymentMethod[]; }>>' is not assignable to parameter of type '() => Promise<QueryObserverResult<ICreditCard[]>>'.
  Type 'QueryObserverResult<{ codAvailable: boolean; }>' is not assignable to type 'QueryObserverResult<ICreditCard[]>'.
"""


def run(script, *args, payload=None, cwd=None):
    p = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)],
                       input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True, cwd=cwd)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, p.stdout + p.stderr


def hook(mode, file_path):
    p = subprocess.run([sys.executable, "-I", str(HOOKS / "gate_guard.py"), mode], input=json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}), capture_output=True, text=True)
    return json.loads(p.stdout) if p.stdout.strip() else None


class Fixture:
    def __init__(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="ei-708-"))
        self.repo, self.session = self.root / "TakeIN", self.root / "session"
        for f, t in BEFORE.items():
            p = self.repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(t)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c07f9c66 parent of #708")
        self.session.mkdir()
        self.decisions = self.session / "decisions.json"
        (self.root / "history.json").write_text(json.dumps(REVIEW_HISTORY))
        (self.root / "history-figma.json").write_text(json.dumps(REVIEW_HISTORY + FIGMA_REQUESTS))
        (self.root / "tsc-baseline.txt").write_text(TSC_BASELINE)
        (self.root / "tsc-after.txt").write_text(TSC_AFTER)
        fake = self.root / "fake_tsc.py"
        fake.write_text("import pathlib, sys\nt = (pathlib.Path(sys.argv[0]).parent / 'tsc-current.txt').read_text()\n"
                        "print(t, end='')\nsys.exit(2 if 'error' in t else 0)\n")
        self.fake_tsc = fake

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, check=True)

    def apply_pr(self):
        for f, t in AFTER.items():
            (self.repo / f).write_text(t)

    def tsc_cmd(self, which):
        """The same command every time (as a real `npx tsc --noEmit` would be); `which` picks the output it prints."""
        (self.root / "tsc-current.txt").write_text((self.root / f"tsc-{which}.txt").read_text())
        return f"{sys.executable} -I {self.fake_tsc}"

    def cleanup(self):
        reg = run("impact_check.py", "finish", self.session) if (self.session / "impact.json").is_file() else None
        shutil.rmtree(self.root, ignore_errors=True)
        return reg
