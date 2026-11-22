package shelter.minecraft.inventory;

import io.papermc.paper.event.player.AsyncChatEvent;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.GameMode;
import org.bukkit.Material;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.enchantments.Enchantment;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.ClickType;
import org.bukkit.event.inventory.InventoryAction;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryDragEvent;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.InventoryHolder;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.PlayerInventory;
import org.bukkit.plugin.java.JavaPlugin;

public class ShelterInventory extends JavaPlugin implements Listener {
    private static final int SIZE = 54;
    private static final int FIRST_EQUIPMENT = 45;
    private static final EquipmentSlot[] EQUIPMENT = {
        EquipmentSlot.HEAD, EquipmentSlot.CHEST, EquipmentSlot.LEGS,
        EquipmentSlot.FEET, EquipmentSlot.HAND, EquipmentSlot.OFF_HAND
    };
    private final Map<UUID, UUID> linked = new ConcurrentHashMap<>();
    private final Map<UUID, View> views = new HashMap<>();

    private final class View implements InventoryHolder {
        private final UUID owner;
        private final UUID companion;
        private final Inventory inventory;

        private View(Player owner, Player companion) {
            this.owner = owner.getUniqueId();
            this.companion = companion.getUniqueId();
            inventory = getServer().createInventory(this, SIZE, Component.text(companion.getName()));
        }

        @Override public Inventory getInventory() { return inventory; }
    }

    @Override public void onEnable() {
        if (!getServer().getOnlineMode()) {
            getLogger().warning("ShelterInventory requires a server that authenticates players.");
            getServer().getPluginManager().disablePlugin(this);
            return;
        }
        var stored = getConfig().getConfigurationSection("links");
        if (stored != null) {
            for (String id : stored.getKeys(false)) {
                try {
                    linked.put(UUID.fromString(id), UUID.fromString(stored.getString(id, "")));
                } catch (IllegalArgumentException ex) {
                    getLogger().warning("Ignored an invalid companion link.");
                }
            }
        }
        getServer().getPluginManager().registerEvents(this, this);
        getServer().getScheduler().runTaskTimer(this, this::refresh, 1, 2);
    }

    @Override public void onDisable() {
        for (View view : new ArrayList<>(views.values())) close(view);
        views.clear();
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String alias, String[] args) {
        if (!(sender instanceof Player owner)) return false;
        if (args.length == 1 && args[0].equalsIgnoreCase("open")) {
            open(owner);
            return true;
        }
        if (!owner.hasPermission("shelterinventory.link")) {
            owner.sendMessage(Component.text("Для привязки напарника нужно разрешение владельца сервера."));
            return true;
        }
        UUID ownerId = owner.getUniqueId();
        if (args.length == 1 && args[0].equalsIgnoreCase("unlink")) {
            linked.remove(ownerId);
            saveLink(ownerId, null);
            var view = views.get(ownerId);
            if (view != null) close(view);
            owner.sendMessage(Component.text("Доступ к инвентарю напарника отключён."));
            return true;
        }
        if (args.length != 2 || !args[0].equalsIgnoreCase("link")) return false;
        Player companion = getServer().getPlayerExact(args[1]);
        if (companion == null || companion.equals(owner) || linked.containsKey(companion.getUniqueId())
                || linked.containsValue(ownerId) || linked.entrySet().stream().anyMatch(entry ->
                !entry.getKey().equals(ownerId) && entry.getValue().equals(companion.getUniqueId()))) {
            owner.sendMessage(Component.text("Укажите ник подключённого отдельного напарника без другой привязки."));
            return true;
        }
        linked.put(ownerId, companion.getUniqueId());
        saveLink(ownerId, companion.getUniqueId().toString());
        owner.sendMessage(Component.text("Инвентарь " + companion.getName() + " подключён. Команда !inv открывает его рядом с напарником."));
        return true;
    }

    private void saveLink(UUID owner, String companion) {
        getConfig().set("links." + owner, companion);
        saveConfig();
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onChat(AsyncChatEvent event) {
        String text = PlainTextComponentSerializer.plainText().serialize(event.originalMessage()).strip();
        var owner = event.getPlayer();
        if (!linked.containsKey(owner.getUniqueId())
                || !(text.equalsIgnoreCase("!inv") || text.equalsIgnoreCase("!инвентарь"))) return;
        event.setCancelled(true);
        getServer().getScheduler().runTask(this, () -> open(owner));
    }

    private void open(Player owner) {
        UUID target = linked.get(owner.getUniqueId());
        Player companion = target == null ? null : getServer().getPlayer(target);
        if (!near(owner, companion)) {
            owner.sendMessage(Component.text(target == null
                    ? "Сначала привяжите напарника командой /shelterinventory link <ник>."
                    : "Подойдите к подключённому напарнику ближе чем на восемь блоков."));
            return;
        }
        var view = new View(owner, companion);
        paint(view, companion.getInventory());
        if (owner.openInventory(view.inventory) != null) views.put(view.owner, view);
    }

    private static boolean near(Player owner, Player companion) {
        return owner != null && companion != null && owner.isOnline() && companion.isOnline()
                && owner.getGameMode() != GameMode.SPECTATOR && !owner.isDead() && !companion.isDead()
                && owner.getWorld().equals(companion.getWorld()) && owner.getLocation().distanceSquared(companion.getLocation()) < 64;
    }

    private Player target(View view, Player owner) {
        if (!view.owner.equals(owner.getUniqueId()) || views.get(view.owner) != view
                || !view.companion.equals(linked.get(view.owner))) return null;
        Player companion = getServer().getPlayer(view.companion);
        return near(owner, companion) ? companion : null;
    }

    private void refresh() {
        for (View view : new ArrayList<>(views.values())) {
            Player owner = getServer().getPlayer(view.owner);
            if (owner == null || owner.getOpenInventory().getTopInventory().getHolder() != view) {
                views.remove(view.owner, view);
                continue;
            }
            Player companion = target(view, owner);
            if (companion == null) close(view);
            else paint(view, companion.getInventory());
        }
    }

    private void close(View view) {
        views.remove(view.owner, view);
        Player owner = getServer().getPlayer(view.owner);
        if (owner != null && owner.getOpenInventory().getTopInventory().getHolder() == view) owner.closeInventory();
    }

    private static EquipmentSlot equipment(int slot) {
        int index = slot - FIRST_EQUIPMENT;
        return index >= 0 && index < EQUIPMENT.length ? EQUIPMENT[index] : null;
    }

    private static int storage(int slot) { return slot < 27 ? slot + 9 : slot - 27; }

    private static boolean editable(int slot) { return slot >= 0 && (slot < 36 || equipment(slot) != null); }

    private static ItemStack copy(ItemStack stack) { return empty(stack) ? null : stack.clone(); }

    private static boolean empty(ItemStack stack) { return stack == null || stack.getType().isAir() || stack.getAmount() <= 0; }

    private static ItemStack read(PlayerInventory inventory, int slot) {
        var equipment = equipment(slot);
        return copy(equipment != null ? inventory.getItem(equipment) : inventory.getItem(storage(slot)));
    }

    private static void write(PlayerInventory inventory, int slot, ItemStack stack) {
        var equipment = equipment(slot);
        if (equipment == null) inventory.setItem(storage(slot), copy(stack));
        else inventory.setItem(equipment, copy(stack));
    }

    private static boolean armor(EquipmentSlot slot) {
        return slot == EquipmentSlot.HEAD || slot == EquipmentSlot.CHEST
                || slot == EquipmentSlot.LEGS || slot == EquipmentSlot.FEET;
    }

    protected EquipmentSlot defaultEquipmentSlot(ItemStack item) {
        var meta = item.getItemMeta();
        return meta != null && meta.hasEquippable() ? meta.getEquippable().getSlot() : item.getType().getEquipmentSlot();
    }

    private boolean accepts(int slot, ItemStack stack) {
        return empty(stack) || !armor(equipment(slot)) || (equipment(slot) == defaultEquipmentSlot(stack)
                && stack.getAmount() == 1);
    }

    private static void paint(View view, PlayerInventory inventory) {
        for (int slot = 0; slot < SIZE; slot++) {
            if (!editable(slot)) continue;
            ItemStack stack = display(inventory, slot);
            if (!Objects.equals(stack, copy(view.inventory.getItem(slot)))) view.inventory.setItem(slot, stack);
        }
    }

    private static ItemStack display(PlayerInventory inventory, int slot) {
        if (slot == 27 + inventory.getHeldItemSlot()) return marker("Выбранный слот — в строке экипировки / Equipped slot below");
        ItemStack stack = read(inventory, slot);
        if (stack != null || equipment(slot) == null) return stack;
        return marker(switch (equipment(slot)) {
            case HEAD -> "Шлем / Head";
            case CHEST -> "Нагрудник / Chest";
            case LEGS -> "Поножи / Legs";
            case FEET -> "Ботинки / Feet";
            case HAND -> "Основная рука / Main hand";
            case OFF_HAND -> "Вторая рука / Off hand";
            default -> "Экипировка / Equipment";
        });
    }

    private static ItemStack marker(String label) {
        var item = new ItemStack(Material.GRAY_STAINED_GLASS_PANE);
        item.editMeta(meta -> meta.displayName(Component.text(label)));
        return item;
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onClick(InventoryClickEvent event) {
        if (!(event.getView().getTopInventory().getHolder() instanceof View view)
                || !(event.getWhoClicked() instanceof Player owner)) return;
        int slot = event.getRawSlot();
        boolean top = slot >= 0 && slot < SIZE;
        Player companion = target(view, owner);
        if (companion == null || top || event.isShiftClick() || event.getAction() == InventoryAction.COLLECT_TO_CURSOR) {
            event.setCancelled(true);
        } else {
            return;
        }
        if (companion == null) {
            getServer().getScheduler().runTask(this, () -> close(view));
            return;
        }
        PlayerInventory inventory = companion.getInventory();
        if (top && editable(slot) && slot != 27 + inventory.getHeldItemSlot()) {
            ItemStack current = read(inventory, slot);
            if (!Objects.equals(display(inventory, slot), copy(event.getCurrentItem()))) {
                paint(view, inventory);
                return;
            }
            if (armor(equipment(slot)) && current != null && current.containsEnchantment(Enchantment.BINDING_CURSE)
                    && companion.getGameMode() != GameMode.CREATIVE) return;
            if (event.isShiftClick()) {
                if (current != null) write(inventory, slot, insert(owner.getInventory(), current));
            } else if (event.getClick() == ClickType.LEFT || event.getClick() == ClickType.RIGHT) {
                moveCursor(event, inventory, slot, current);
            }
        } else if (!top && event.isShiftClick() && event.getClickedInventory() instanceof PlayerInventory) {
            ItemStack stack = copy(event.getCurrentItem());
            if (stack != null) {
                var matching = defaultEquipmentSlot(stack);
                if (armor(matching) && empty(inventory.getItem(matching))) {
                    inventory.setItem(matching, withCount(stack, 1));
                    stack = withCount(stack, stack.getAmount() - 1);
                }
                event.setCurrentItem(stack == null ? null : insert(inventory, stack));
            }
        }
        paint(view, inventory);
    }

    // Bukkit returns the remainder. Passing a clone avoids the implementation's in-place count changes.
    private static ItemStack insert(PlayerInventory destination, ItemStack stack) {
        return destination.addItem(stack.clone()).get(0);
    }

    private void moveCursor(InventoryClickEvent event, PlayerInventory inventory, int slot, ItemStack current) {
        ItemStack cursor = copy(event.getView().getCursor());
        boolean single = event.getClick() == ClickType.RIGHT;
        if (cursor == null) {
            if (current == null) return;
            int amount = single ? (current.getAmount() + 1) / 2 : current.getAmount();
            event.getView().setCursor(withCount(current, amount));
            write(inventory, slot, withCount(current, current.getAmount() - amount));
        } else if (current == null || current.isSimilar(cursor)) {
            int before = current == null ? 0 : current.getAmount();
            int max = armor(equipment(slot)) ? 1 : cursor.getMaxStackSize();
            int moved = Math.min(max - before, single ? 1 : cursor.getAmount());
            if (moved <= 0) return;
            ItemStack stack = withCount(cursor, before + moved);
            if (!accepts(slot, stack)) return;
            write(inventory, slot, stack);
            event.getView().setCursor(withCount(cursor, cursor.getAmount() - moved));
        } else if (accepts(slot, cursor)) {
            write(inventory, slot, cursor);
            event.getView().setCursor(current);
        }
    }

    private static ItemStack withCount(ItemStack stack, int count) {
        if (count <= 0) return null;
        ItemStack result = stack.clone();
        result.setAmount(count);
        return result;
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onDrag(InventoryDragEvent event) {
        if (event.getView().getTopInventory().getHolder() instanceof View
                && event.getRawSlots().stream().anyMatch(slot -> slot < SIZE)) event.setCancelled(true);
    }
}
