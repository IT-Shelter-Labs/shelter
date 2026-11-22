package shelter.minecraft.inventory;

import io.papermc.paper.chat.ChatRenderer;
import io.papermc.paper.event.player.AsyncChatEvent;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import net.kyori.adventure.chat.SignedMessage;
import net.kyori.adventure.text.Component;
import org.bukkit.Material;
import org.bukkit.event.inventory.ClickType;
import org.bukkit.event.inventory.InventoryAction;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryType;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.EquipmentSlot;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockbukkit.mockbukkit.MockBukkit;
import org.mockbukkit.mockbukkit.entity.PlayerMock;

import static org.junit.jupiter.api.Assertions.*;

public class ShelterInventoryTest {
    public static class TestPlugin extends ShelterInventory {
        @Override protected EquipmentSlot defaultEquipmentSlot(ItemStack item) {
            // MockBukkit leaves vanilla item components unimplemented.
            return item.getType() == Material.IRON_HELMET ? EquipmentSlot.HEAD : EquipmentSlot.HAND;
        }
    }

    private ShelterInventory plugin;
    private PlayerMock owner;
    private PlayerMock companion;

    @BeforeEach void setup() throws IOException {
        var server = MockBukkit.mock();
        server.setOnlineMode(true);
        try (var source = ShelterInventory.class.getResourceAsStream("/plugin.yml")) {
            assertNotNull(source);
            var descriptor = new String(source.readAllBytes(), StandardCharsets.UTF_8)
                    .replace(ShelterInventory.class.getName(), TestPlugin.class.getName());
            plugin = MockBukkit.loadWith(TestPlugin.class,
                    new ByteArrayInputStream(descriptor.getBytes(StandardCharsets.UTF_8)));
        }
        owner = server.addPlayer("HomeOwner");
        companion = server.addPlayer("JarvisTester");
        owner.setOp(true);
        assertTrue(owner.performCommand("shelterinventory link JarvisTester"));
    }

    @AfterEach void close() {
        MockBukkit.unmock();
    }

    @Test void exchangesStorageAndEquipmentThroughTheLiveMenu() {
        companion.getInventory().setItem(9, new ItemStack(Material.COBBLESTONE, 8));
        var text = Component.text("!inv");
        var chat = new AsyncChatEvent(true, owner, Set.of(), ChatRenderer.defaultRenderer(), text, text,
                SignedMessage.system("!inv", text));
        plugin.onChat(chat);
        assertTrue(chat.isCancelled());
        MockBukkit.getMock().getScheduler().performOneTick();
        var view = owner.getOpenInventory();
        assertEquals(54, view.getTopInventory().getSize());
        assertEquals(8, view.getItem(0).getAmount());

        assertTrue(click(0, ClickType.SHIFT_LEFT, InventoryAction.MOVE_TO_OTHER_INVENTORY).isCancelled());
        assertNull(companion.getInventory().getItem(9));
        assertEquals(8, owner.getInventory().getItem(0).getAmount());

        view.setItem(55, new ItemStack(Material.IRON_HELMET));
        assertEquals(Material.IRON_HELMET, view.getItem(55).getType());
        assertTrue(click(55, ClickType.SHIFT_LEFT, InventoryAction.MOVE_TO_OTHER_INVENTORY).isCancelled());
        assertNull(view.getItem(55));
        assertEquals(Material.IRON_HELMET, companion.getInventory().getHelmet().getType());

        owner.getOpenInventory().setCursor(new ItemStack(Material.DIAMOND_SWORD));
        assertTrue(click(45, ClickType.LEFT, InventoryAction.SWAP_WITH_CURSOR).isCancelled());
        assertEquals(Material.DIAMOND_SWORD, owner.getOpenInventory().getCursor().getType());
        assertEquals(Material.IRON_HELMET, companion.getInventory().getHelmet().getType());

        assertTrue(click(49, ClickType.LEFT, InventoryAction.PLACE_ALL).isCancelled());
        assertEquals(Material.DIAMOND_SWORD, companion.getInventory().getItemInMainHand().getType());
        assertEquals(Material.GRAY_STAINED_GLASS_PANE, view.getItem(27).getType());
    }

    @Test void rejectsStaleDisplayAndOtherPlayers() {
        companion.getInventory().setItem(9, new ItemStack(Material.STONE, 2));
        owner.performCommand("shelterinventory open");
        companion.getInventory().setItem(9, new ItemStack(Material.DIAMOND, 3));
        assertTrue(click(0, ClickType.LEFT, InventoryAction.PICKUP_ALL).isCancelled());
        assertEquals(Material.DIAMOND, companion.getInventory().getItem(9).getType());
        assertEquals(Material.DIAMOND, owner.getOpenInventory().getItem(0).getType());
        var stranger = MockBukkit.getMock().addPlayer("Stranger");
        stranger.performCommand("shelterinventory open");
        assertEquals(InventoryType.CRAFTING, stranger.getOpenInventory().getType());
    }

    private InventoryClickEvent click(int slot, ClickType click, InventoryAction action) {
        var event = new InventoryClickEvent(owner.getOpenInventory(), InventoryType.SlotType.CONTAINER, slot, click, action);
        plugin.onClick(event);
        return event;
    }
}
