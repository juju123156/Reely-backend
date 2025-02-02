package com.reely.serviceImpl;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.reely.dto.SettingDto;
import com.reely.mapper.SettingMapper;
import com.reely.service.SettingService;

@Transactional
@Service
public class SettingServiceImpl implements SettingService {

    private final SettingMapper settingMapper;

    @Autowired
    public SettingServiceImpl(SettingMapper settingMapper) {
        this.settingMapper = settingMapper;
    }
    @Override
    public List<SettingDto> getFaqList() {
        return settingMapper.findAll();
    }
}
