package com.example.api;

import com.example.api.controllers.ItemsController;
import com.example.api.dto.CreateItemRequest;
import com.example.api.dto.ItemResponse;
import com.example.api.services.ItemService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import java.time.Instant;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(ItemsController.class)
class ItemsControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private ItemService itemService;

    @Test
    void createItemReturns201() throws Exception {
        CreateItemRequest req = new CreateItemRequest("first item", "desc");
        ItemResponse resp = new ItemResponse(1L, 42L, "first item", "desc", Instant.now());
        when(itemService.createItem(anyLong(), any())).thenReturn(resp);

        mockMvc.perform(post("/api/items")
                .header("Authorization", "Bearer fake-jwt")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(req)))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.title").value("first item"));
    }
}
